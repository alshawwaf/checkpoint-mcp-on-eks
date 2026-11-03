"""`chkpmcpeks destroy` -- remove everything this stack created, in the order
EKS needs, then prove nothing is left.

  1. Helm release  -> the Auto Mode controller deletes the ALB and its security groups
  2. wait until no load balancer remains in the stack's VPC
  3. add-ons (Reloader, External Secrets) and the Graviton NodePool -> nodes terminate
  4. terraform destroy platform (cluster, VPC, NAT, Cognito, roles, ACM, stack secrets)
  5. CloudWatch log groups the add-ons created outside Terraform
  6. terraform destroy build (ECR + images, CodeBuild, bucket)   unless --keep-images
  7. scan for anything still tagged project=chkp-mcp-eks

The per-server `chkp/<server>` secrets are NEVER deleted: they hold Check Point
credentials and may be shared with the AgentCore deployment.
"""

from __future__ import annotations

import sys
import time

from . import terraform, ui
from .awsutil import BotoCoreError, ClientError, caller_identity, log, paginate
from .deploy import iam_principal_arn
from .kube import PLATFORM_MANIFEST
from .stack import Stack

STEPS = ["Plan", "Workloads + load balancer", "Add-ons + NodePool", "Platform (Terraform)",
         "Log groups", "Build stack (Terraform)", "Leftover scan"]


def _confirm(args, plan):
    for line in plan:
        log(line)
    if args.yes:
        return True
    if not sys.stdin.isatty():
        log("Non-interactive shell: re-run with --yes to confirm.")
        return False
    try:
        return input("\nDestroy all of the above? [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _wait_no_lbs(session, region, vpc_id, attempts=60, delay=10):
    elb = session.client("elbv2", region_name=region)
    for i in range(attempts):
        lbs = [lb for lb in paginate(elb.describe_load_balancers) if lb.get("VpcId") == vpc_id]
        if not lbs:
            return True
        if i % 6 == 0:
            log(f"  waiting for {len(lbs)} load balancer(s) to be deleted: {', '.join(lb['LoadBalancerName'] for lb in lbs)}")
        time.sleep(delay)
    return False


def _cleanup_vpc_leftovers(session, region, vpc_id):
    """Security groups / ENIs the load balancer controller or Auto Mode left in the
    VPC; they block VPC deletion. Only touches non-default SGs inside OUR VPC."""
    ec2 = session.client("ec2", region_name=region)
    try:
        for eni in ec2.describe_network_interfaces(Filters=[{"Name": "vpc-id", "Values": [vpc_id]},
                                                            {"Name": "status", "Values": ["available"]}])["NetworkInterfaces"]:
            log(f"  deleting detached ENI {eni['NetworkInterfaceId']}")
            ec2.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
        sgs = ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])["SecurityGroups"]
        sgs = [g for g in sgs if g["GroupName"] != "default"]
        for g in sgs:   # drop cross-references first
            for perm_key, revoke in (("IpPermissions", ec2.revoke_security_group_ingress),
                                     ("IpPermissionsEgress", ec2.revoke_security_group_egress)):
                perms = [p for p in g.get(perm_key, []) if p.get("UserIdGroupPairs")]
                if perms:
                    try:
                        revoke(GroupId=g["GroupId"], IpPermissions=perms)
                    except ClientError:
                        pass
        for g in sgs:
            try:
                ec2.delete_security_group(GroupId=g["GroupId"])
                log(f"  deleted leftover security group {g['GroupName']}")
            except ClientError:
                pass
    except (ClientError, BotoCoreError) as e:
        log(f"  VPC leftover cleanup skipped: {e}")


def _delete_log_groups(session, region, cluster):
    logs = session.client("logs", region_name=region)
    gone = []
    for prefix in (f"/aws/containerinsights/{cluster}/", f"/aws/eks/{cluster}/"):
        for g in paginate(logs.describe_log_groups, logGroupNamePrefix=prefix):
            try:
                logs.delete_log_group(logGroupName=g["logGroupName"])
                gone.append(g["logGroupName"])
            except ClientError:
                pass
    log(f"  deleted {len(gone)} log group(s)" + (f": {', '.join(gone)}" if gone else ""))


_GONE_CODES = {"InvalidInstanceID.NotFound", "InvalidVolume.NotFound", "InvalidGroup.NotFound",
               "InvalidSecurityGroupRuleId.NotFound", "InvalidSubnetID.NotFound", "InvalidVpcID.NotFound",
               "NatGatewayNotFound", "InvalidAllocationID.NotFound", "ResourceNotFoundException"}


def still_exists(session, region, arn):
    """Ask the owning service whether a resource the tagging index still lists is really
    there. The index lags deletions by minutes, so a just-destroyed stack always shows a few
    stale entries. Returns False only when the service confirms the resource is gone;
    unknown types count as present, so nothing real is ever hidden."""
    service, resource = arn.split(":")[2], arn.split(":", 5)[5]
    kind, _, rid = resource.partition("/")
    try:
        if service == "ec2":
            ec2 = session.client("ec2", region_name=region)
            if kind == "instance":
                inst = ec2.describe_instances(InstanceIds=[rid])["Reservations"][0]["Instances"][0]
                return inst["State"]["Name"] not in ("terminated", "shutting-down")
            if kind == "natgateway":
                return ec2.describe_nat_gateways(NatGatewayIds=[rid])["NatGateways"][0]["State"] not in ("deleted", "deleting")
            calls = {"volume": lambda: ec2.describe_volumes(VolumeIds=[rid]),
                     "security-group": lambda: ec2.describe_security_groups(GroupIds=[rid]),
                     "security-group-rule": lambda: ec2.describe_security_group_rules(SecurityGroupRuleIds=[rid]),
                     "subnet": lambda: ec2.describe_subnets(SubnetIds=[rid]),
                     "vpc": lambda: ec2.describe_vpcs(VpcIds=[rid]),
                     "elastic-ip": lambda: ec2.describe_addresses(AllocationIds=[rid])}
            if kind in calls:
                calls[kind]()
                return True
        elif service == "cognito-idp" and kind == "userpool":
            session.client("cognito-idp", region_name=region).describe_user_pool(UserPoolId=rid)
            return True
        elif service == "eks" and kind in ("cluster", "podidentityassociation"):
            session.client("eks", region_name=region).describe_cluster(name=rid.split("/")[0])
            return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in _GONE_CODES:
            return False
        raise
    except (IndexError, KeyError):
        return False
    return True


def leftovers(session, cfg):
    """(present, stale): resources still tagged for this stack, split into ones that really
    exist and index entries for resources the owning service confirms are deleted."""
    tag = session.client("resourcegroupstaggingapi", region_name=cfg.region)
    present, stale = [], []
    for r in paginate(tag.get_resources, TagFilters=[{"Key": "project", "Values": ["chkp-mcp-eks"]},
                                                      {"Key": "stack", "Values": [cfg.stack_tag]}]):
        arn = r["ResourceARN"]
        if ":secret:chkp/" in arn:
            continue   # Check Point credential secrets are kept by design
        (present if still_exists(session, cfg.region, arn) else stale).append(arn)
    return present, stale


def run(cfg, session, args, profile=None):
    st = Stack(cfg, session, profile)
    build_out = terraform.outputs("build", profile, cfg.prefix)
    plan = ["", "chkpmcpeks destroy will remove:"]
    if st.deployed:
        plan += [f"  - EKS cluster {st.out['cluster_name']}, its nodes, ALB, VPC {st.out['vpc_id']} and NAT gateway",
                 f"  - Cognito pool {st.out['cognito_user_pool_id']}, Pod Identity roles, ACM certificate, stack secrets",
                 "  - CloudWatch log groups created by the observability add-on"]
    if build_out and not args.keep_images:
        plan += [f"  - ECR repositories {build_out.get('server_repository')}, {build_out.get('agent_repository')} "
                 "(with images), CodeBuild project, source bucket"]
    plan += ["  KEPT: the chkp/<server> credential secrets (shared with the AgentCore project)"]
    if len(plan) == 3:
        log("Nothing deployed by this stack -- nothing to destroy.")
        return 0
    if not _confirm(args, plan):
        return 1

    rep = ui.Reporter("destroy", STEPS, context=f"{cfg.region} · {cfg.cluster_name}")
    rep.begin("Plan")
    ok = True
    if st.deployed:
        reachable = True
        try:
            kube = st.kube   # connects: directly, or through the SSM tunnel to the private endpoint
            reachable = kube.wait_api(attempts=3, delay=5)
        except (ClientError, BotoCoreError, RuntimeError, SystemExit) as e:
            log(f"  Kubernetes API not reachable ({e}); Terraform will still remove everything")
            kube, reachable = None, False
        rep.begin("Workloads + load balancer")
        if reachable:
            kube.uninstall(cfg.helm_release, cfg.namespace)
            kube.kubectl("delete", "ingressclass", "chkp-mcp-alb", "--ignore-not-found", check=False)
            kube.kubectl("delete", "ingressclassparams", "chkp-mcp-alb", "--ignore-not-found", check=False)
        if not _wait_no_lbs(session, cfg.region, st.out["vpc_id"]):
            log("  WARNING: a load balancer is still present; continuing (terraform may need a re-run)")
            rep.warn()
        rep.begin("Add-ons + NodePool")
        if reachable:
            kube.uninstall("reloader", "reloader")
            kube.uninstall("external-secrets", "external-secrets")
            kube.kubectl("delete", "-f", PLATFORM_MANIFEST, "--ignore-not-found", "--wait=true", "--timeout=5m",
                         check=False)
        rep.begin("Platform (Terraform)")
        # cluster_admin_principal_arns is a required variable; a stack created before it
        # existed has no saved value. Destroy only needs it to validate, never to grant.
        extra = None
        if not terraform.stack_settings(cfg.prefix).get("cluster_admin_principal_arns"):
            extra = {"cluster_admin_principal_arns": st.out.get("cluster_admin_principal_arns") or
                     [iam_principal_arn(caller_identity(session, cfg.region)["Arn"])]}
        try:
            terraform.destroy("platform", cfg, profile, extra_vars=extra)
        except RuntimeError:
            log("  first destroy attempt failed -- removing VPC leftovers and retrying once")
            _cleanup_vpc_leftovers(session, cfg.region, st.out["vpc_id"])
            terraform.destroy("platform", cfg, profile, extra_vars=extra)
        rep.begin("Log groups")
        _delete_log_groups(session, cfg.region, st.out["cluster_name"])
    else:
        for _ in range(4):
            rep.begin()
            log("  platform not deployed -- skipped")
    rep.begin("Build stack (Terraform)")
    if args.keep_images:
        log("  --keep-images: ECR repositories and CodeBuild kept")
    else:
        terraform.destroy("build", cfg, profile)
    rep.begin("Leftover scan")
    time.sleep(5)
    left, stale = leftovers(session, cfg)
    if stale:
        log(f"  {len(stale)} stale tag-index entr{'y' if len(stale) == 1 else 'ies'} for resources the "
            "owning services confirm are deleted (the index catches up within minutes)")
    if left:
        ok = False
        log("  STILL PRESENT, tagged project=chkp-mcp-eks:")
        for arn in left:
            log(f"    {arn}")
        rep.warn()
    else:
        log("  nothing of this stack remains (chkp/<server> secrets kept by design)")
    rep.close(ok, ["  Stack removed." if ok else "  Re-run `chkpmcpeks destroy` in a few minutes to confirm."])
    return 0 if ok else 1
