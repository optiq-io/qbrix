{{/*
Expand the name of the chart.
*/}}
{{- define "qbrix.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "qbrix.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "qbrix.labels" -}}
helm.sh/chart: {{ include "qbrix.chart" . }}
{{ include "qbrix.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: qbrix
{{- end }}

{{/*
Selector labels
*/}}
{{- define "qbrix.selectorLabels" -}}
app.kubernetes.io/name: {{ include "qbrix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Secret names. Keyed on .Release.Name, like the in-cluster infra services:
subcharts resolve these same names locally, and a fullname would expand
.Chart.Name to the subchart, so this is the only spelling both sides agree on.
*/}}
{{- define "qbrix.postgresSecretName" -}}
{{- if .Values.global.postgres.existingSecret }}
{{- .Values.global.postgres.existingSecret }}
{{- else }}
{{- printf "%s-postgres" .Release.Name }}
{{- end }}
{{- end }}

{{- define "qbrix.redisSecretName" -}}
{{- if .Values.global.redis.existingSecret }}
{{- .Values.global.redis.existingSecret }}
{{- else }}
{{- printf "%s-redis" .Release.Name }}
{{- end }}
{{- end }}

{{- define "qbrix.clickhouseSecretName" -}}
{{- if .Values.global.clickhouse.existingSecret }}
{{- .Values.global.clickhouse.existingSecret }}
{{- else }}
{{- printf "%s-clickhouse" .Release.Name }}
{{- end }}
{{- end }}

{{/*
A generated secret value that survives upgrades: the value already stored under
key in the named secret, else a fresh random one. lookup returns nothing under
helm template, so render-only tools get a new value on every render.
Usage: include "qbrix.persistentSecretValue" (dict "ctx" . "name" $name "key" "password")
*/}}
{{- define "qbrix.persistentSecretValue" -}}
{{- $existing := lookup "v1" "Secret" .ctx.Release.Namespace .name }}
{{- if and $existing $existing.data (hasKey $existing.data .key) }}
{{- index $existing.data .key | b64dec }}
{{- else }}
{{- randAlphaNum 32 }}
{{- end }}
{{- end }}

{{/*
Image pull secrets
*/}}
{{- define "qbrix.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}