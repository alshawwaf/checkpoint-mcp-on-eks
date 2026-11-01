{{/* Common labels */}}
{{- define "chkp.labels" -}}
app.kubernetes.io/part-of: checkpoint-mcp
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* Target / Service name for a server: hyphens dropped (agentgateway target names) */}}
{{- define "chkp.target" -}}
{{- . | replace "-" "" -}}
{{- end -}}

{{/* Kubernetes object name for a server */}}
{{- define "chkp.serverName" -}}
{{- printf "mcp-%s" . -}}
{{- end -}}

{{/* image reference: registry/repo@digest when a digest is known, else :tag */}}
{{- define "chkp.image" -}}
{{- $ref := .repository -}}
{{- if .registry }}{{- $ref = printf "%s/%s" .registry .repository -}}{{- end -}}
{{- if .digest -}}
{{- printf "%s@%s" $ref .digest -}}
{{- else -}}
{{- printf "%s:%s" $ref (required "image tag or digest required" .tag) -}}
{{- end -}}
{{- end -}}

{{/* Restricted pod security context shared by every workload */}}
{{- define "chkp.podSecurity" -}}
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "chkp.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* Scheduling block */}}
{{- define "chkp.scheduling" -}}
{{- with .Values.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
