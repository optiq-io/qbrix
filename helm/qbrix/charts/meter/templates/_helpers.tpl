{{/*
Expand the name of the chart.
*/}}
{{- define "meter.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "meter.fullname" -}}
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
{{- define "meter.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "meter.labels" -}}
helm.sh/chart: {{ include "meter.chart" . }}
{{ include "meter.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: qbrix
app.kubernetes.io/component: meter
{{- end }}

{{/*
Selector labels
*/}}
{{- define "meter.selectorLabels" -}}
app.kubernetes.io/name: {{ include "meter.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "meter.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "meter.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Resolved image tag; also used as the sentry release identifier
*/}}
{{- define "meter.imageTag" -}}
{{- .Values.image.tag | default .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Get the image repository with optional global registry
*/}}
{{- define "meter.image" -}}
{{- $registry := .Values.global.imageRegistry | default "" }}
{{- $repository := .Values.image.repository }}
{{- $tag := include "meter.imageTag" . }}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- else }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}

{{/*
Get redis host
*/}}
{{- define "meter.redisHost" -}}
{{- .Values.global.redis.host | default (printf "%s-redis" .Release.Name) }}
{{- end }}

{{/*
Get postgres host
*/}}
{{- define "meter.postgresHost" -}}
{{- .Values.global.postgres.host | default (printf "%s-postgres" .Release.Name) }}
{{- end }}

{{/*
Get redis secret name
*/}}
{{- define "meter.redisSecretName" -}}
{{- if .Values.global.redis.existingSecret }}
{{- .Values.global.redis.existingSecret }}
{{- else }}
{{- printf "%s-redis" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get postgres secret name
*/}}
{{- define "meter.postgresSecretName" -}}
{{- if .Values.global.postgres.existingSecret }}
{{- .Values.global.postgres.existingSecret }}
{{- else }}
{{- printf "%s-postgres" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get sentry secret name
*/}}
{{- define "meter.sentrySecretName" -}}
{{- if .Values.global.sentry.existingSecret }}
{{- .Values.global.sentry.existingSecret }}
{{- else }}
{{- printf "%s-sentry" .Release.Name }}
{{- end }}
{{- end }}
