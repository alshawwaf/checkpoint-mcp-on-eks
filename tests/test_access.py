"""Private API endpoint, explicit cluster admins, and the SSM tunnel routing."""

from types import SimpleNamespace as NS

from chkpmcpeks import deploy, terraform, tunnel
from chkpmcpeks.config import StackConfig


def test_route_is_tunnel_unless_public_endpoint_admits_this_ip():
    private = {"endpointPublicAccess": False, "publicAccessCidrs": ["0.0.0.0/0"]}
    assert tunnel.choose_route(private, "203.0.113.7") == "tunnel"
    public_other = {"endpointPublicAccess": True, "publicAccessCidrs": ["198.51.100.0/24"]}
    assert tunnel.choose_route(public_other, "203.0.113.7") == "tunnel"
    public_mine = {"endpointPublicAccess": True, "publicAccessCidrs": ["203.0.113.7/32"]}
    assert tunnel.choose_route(public_mine, "203.0.113.7") == "direct"
    assert tunnel.choose_route(public_mine, "") == "tunnel"   # IP unknown -> safe path


def test_tunnel_kubeconfig_keeps_tls_verification_on_the_real_name():
    doc = {"clusters": [{"cluster": {"server": "https://ABC.gr7.us-east-1.eks.amazonaws.com",
                                     "certificate-authority-data": "Q0E="}}]}
    c = tunnel.tunnel_kubeconfig(doc, 50123, "https://ABC.gr7.us-east-1.eks.amazonaws.com")["clusters"][0]["cluster"]
    assert c["server"] == "https://127.0.0.1:50123"
    assert c["tls-server-name"] == "abc.gr7.us-east-1.eks.amazonaws.com"
    assert c["certificate-authority-data"] == "Q0E="


def test_assumed_role_session_becomes_role_arn():
    assert deploy.iam_principal_arn("arn:aws:sts::123456789012:assumed-role/Admins/alice") == \
        "arn:aws:iam::123456789012:role/Admins"
    assert deploy.iam_principal_arn("arn:aws:iam::123456789012:user/ci") == "arn:aws:iam::123456789012:user/ci"


def test_tf_vars_pass_access_settings_with_terraform_types(monkeypatch):
    monkeypatch.setattr(terraform, "stack_settings", lambda prefix="": {
        "cluster_admin_principal_arns": ["arn:aws:iam::123456789012:role/Admins"],
        "cluster_endpoint_public_access": False, "llm_provider": "anthropic"})
    args = terraform.tf_vars(StackConfig())
    assert 'cluster_admin_principal_arns=["arn:aws:iam::123456789012:role/Admins"]' in args
    assert "cluster_endpoint_public_access=false" in args
    assert not any("llm_provider" in a for a in args)


def test_non_interactive_deploy_without_admins_stops_before_spending(monkeypatch):
    saved = {}
    monkeypatch.setattr(terraform, "stack_settings", lambda prefix="": dict(saved))
    monkeypatch.setattr(terraform, "save_stack_settings", lambda prefix, **kw: saved.update(kw))
    monkeypatch.setattr(deploy, "caller_identity",
                        lambda s, r: {"Arn": "arn:aws:sts::123456789012:assumed-role/Admins/me"})
    args = NS(admin_arn=None, yes=True, public_endpoint=False, private_endpoint=False, public_endpoint_cidr=None)
    assert deploy.resolve_access(StackConfig(), None, args) is False
    assert "cluster_admin_principal_arns" not in saved   # nothing granted implicitly


def test_explicit_admin_and_public_endpoint_defaults_to_this_ip(monkeypatch):
    saved = {}
    monkeypatch.setattr(terraform, "stack_settings", lambda prefix="": dict(saved))
    monkeypatch.setattr(terraform, "save_stack_settings", lambda prefix, **kw: saved.update(kw))
    monkeypatch.setattr(tunnel, "public_ip", lambda: "203.0.113.7")
    args = NS(admin_arn=["arn:aws:sts::123456789012:assumed-role/Ops/x"], yes=True, public_endpoint=True,
              private_endpoint=False, public_endpoint_cidr=None)
    assert deploy.resolve_access(StackConfig(), None, args) is True
    assert saved["cluster_admin_principal_arns"] == ["arn:aws:iam::123456789012:role/Ops"]
    assert saved["cluster_endpoint_public_access"] is True
    assert saved["cluster_endpoint_public_access_cidrs"] == ["203.0.113.7/32"]


def test_terraform_security_defaults_stay_hardened():
    import os
    import re

    tf = os.path.join(os.path.dirname(__file__), "..", "terraform", "platform")
    variables = open(os.path.join(tf, "variables.tf"), encoding="utf-8").read()
    main = open(os.path.join(tf, "main.tf"), encoding="utf-8").read()

    def block(name):
        return re.search(r'variable "' + name + r'" \{(.*?)\n\}', variables, re.S).group(1)

    assert re.search(r"default\s*=\s*false", block("cluster_endpoint_public_access"))
    assert "0.0.0.0/0" not in block("cluster_endpoint_public_access_cidrs")
    assert "default" not in block("cluster_admin_principal_arns")          # required, no implicit admin
    assert re.search(r"enable_cluster_creator_admin_permissions\s*=\s*false", main)
    assert re.search(r"endpoint_public_access\s*=\s*var\.cluster_endpoint_public_access\b", main)
    assert re.search(r'authentication_mode\s*=\s*"API"', main)


class _FakeSession:
    """Answers like real AWS: ids in `alive` exist, everything else is NotFound."""

    def __init__(self, alive=(), terminated=()):
        self.alive, self.terminated = set(alive), set(terminated)

    def client(self, name, region_name=None):
        from botocore.exceptions import ClientError

        def nf(code):
            raise ClientError({"Error": {"Code": code, "Message": "x"}}, "Describe")

        alive, terminated = self.alive, self.terminated

        class C:
            def describe_instances(self, InstanceIds):
                i = InstanceIds[0]
                if i in terminated:
                    return {"Reservations": [{"Instances": [{"State": {"Name": "terminated"}}]}]}
                return {"Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]} if i in alive \
                    else nf("InvalidInstanceID.NotFound")

            def describe_security_groups(self, GroupIds):
                return {} if GroupIds[0] in alive else nf("InvalidGroup.NotFound")

            def describe_user_pool(self, UserPoolId):
                return {} if UserPoolId in alive else nf("ResourceNotFoundException")

        return C()


def test_leftover_scan_hides_only_confirmed_deletions():
    from chkpmcpeks.destroy import still_exists

    a = "arn:aws:ec2:us-east-1:123456789012:"
    s = _FakeSession(alive={"sg-live", "us-east-1_live"}, terminated={"i-gone"})
    assert still_exists(s, "us-east-1", a + "instance/i-gone") is False
    assert still_exists(s, "us-east-1", a + "security-group/sg-dead") is False
    assert still_exists(s, "us-east-1", a + "security-group/sg-live") is True
    assert still_exists(s, "us-east-1", "arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_live") is True
    # a type the scan cannot check is always reported, never hidden
    assert still_exists(s, "us-east-1", "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/x/1") is True
