t{{/*
Expand the name of the chart.
*/}}
{{- define "qbrix.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "qbrix.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
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
Postgres secret name
*/}}
{{- define "qbrix.postgresSecretName" -}}
{{- if .Values.global.postgres.existingSecret }}
{{- .Values.global.postgres.existingSecret }}
{{- else }}
{{- include "qbrix.fullname" . }}-postgres
{{- end }}
{{- end }}

{{/*
Redis secret name
*/}}
{{- define "qbrix.redisSecretName" -}}
{{- if .Values.global.redis.existingSecret }}
{{- .Values.global.redis.existingSecret }}
{{- else }}
{{- include "qbrix.fullname" . }}-redis
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