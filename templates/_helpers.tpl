{{/*
Fullname — just the agentName, truncated to 63 chars.
*/}}
{{- define "kubeclaw.fullname" -}}
{{- required "agentName is required" .Values.agentName | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Namespace — devpod-{agentName}
*/}}
{{- define "kubeclaw.namespace" -}}
devpod-{{ include "kubeclaw.fullname" . }}
{{- end }}

{{/*
Display name — agentDisplayName or "{agentName} Dev"
*/}}
{{- define "kubeclaw.displayName" -}}
{{- if .Values.agentDisplayName }}
{{- .Values.agentDisplayName }}
{{- else }}
{{- printf "%s Dev" (include "kubeclaw.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Agent ID — agent.id or agentName
*/}}
{{- define "kubeclaw.agentId" -}}
{{- if .Values.agent.id }}
{{- .Values.agent.id }}
{{- else }}
{{- include "kubeclaw.fullname" . }}
{{- end }}
{{- end }}

{{/*
Workspace — agent.workspace or first repo path or /data/workspace
*/}}
{{- define "kubeclaw.workspace" -}}
{{- if .Values.agent.workspace }}
{{- .Values.agent.workspace }}
{{- else if .Values.git.repos }}
{{- (index .Values.git.repos 0).path }}
{{- else -}}
/data/workspace
{{- end }}
{{- end }}

{{/*
Mention patterns — agent.mentionPatterns or ["@{agentName}", "{agentName}"]
*/}}
{{- define "kubeclaw.mentionPatterns" -}}
{{- if .Values.agent.mentionPatterns }}
{{- .Values.agent.mentionPatterns | toJson }}
{{- else }}
{{- list (printf "@%s" (include "kubeclaw.fullname" .)) (include "kubeclaw.fullname" .) | toJson }}
{{- end }}
{{- end }}

{{/*
Secret name — existingSecret or {fullname}-secrets
*/}}
{{- define "kubeclaw.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "kubeclaw.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Chart name and version for chart label.
*/}}
{{- define "kubeclaw.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kubeclaw.labels" -}}
helm.sh/chart: {{ include "kubeclaw.chart" . }}
{{ include "kubeclaw.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: openclaw-devpods
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kubeclaw.selectorLabels" -}}
app.kubernetes.io/name: devpod
app.kubernetes.io/instance: {{ include "kubeclaw.fullname" . }}
app.kubernetes.io/component: ai-agent
{{- end }}

{{/*
PVC name — persistence.existingClaim or {fullname}-data
*/}}
{{- define "kubeclaw.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- printf "%s-data" (include "kubeclaw.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Whether any workflows are defined.
*/}}
{{- define "kubeclaw.hasWorkflows" -}}
{{- if .Values.workflows }}
{{- if gt (len .Values.workflows) 0 }}true{{- end }}
{{- end }}
{{- end }}

{{/*
Workflow ServiceAccount name — {agentName}-workflow
*/}}
{{- define "kubeclaw.workflowSaName" -}}
{{- printf "%s-workflow" (include "kubeclaw.fullname" .) }}
{{- end }}

{{/*
Workflow labels — standard labels with workflow component
*/}}
{{- define "kubeclaw.workflowLabels" -}}
helm.sh/chart: {{ include "kubeclaw.chart" . }}
app.kubernetes.io/name: devpod
app.kubernetes.io/instance: {{ include "kubeclaw.fullname" . }}
app.kubernetes.io/component: workflow
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: openclaw-devpods
{{- end }}

{{/*
Workflow agent ID — uses workflow-level agent override or chart default
*/}}
{{- define "kubeclaw.workflowAgentId" -}}
{{- if .agent }}
{{- .agent }}
{{- else }}
{{- include "kubeclaw.agentId" .root }}
{{- end }}
{{- end }}
