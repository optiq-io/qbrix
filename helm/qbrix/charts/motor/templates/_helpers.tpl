{{/*
Expand the name of the chart.
*/}}
{{- define "motor.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "motor.fullname" -}}
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
{{- define "motor.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "motor.labels" -}}
helm.sh/chart: {{ include "motor.chart" . }}
{{ include "motor.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: qbrix
app.kubernetes.io/component: motor
{{- end }}

{{/*
Selector labels
*/}}
{{- define "motor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "motor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "motor.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "motor.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Resolved image tag; also used as the sentry release identifier
*/}}
{{- define "motor.imageTag" -}}
{{- .Values.image.tag | default .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Get the image repository with optional global registry
*/}}
{{- define "motor.image" -}}
{{- $registry := .Values.global.imageRegistry | default "" }}
{{- $repository := .Values.image.repository }}
{{- $tag := include "motor.imageTag" . }}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- else }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}

{{/*
Get redis host
*/}}
{{- define "motor.redisHost" -}}
{{- .Values.global.redis.host | default (printf "%s-redis" .Release.Name) }}
{{- end }}

{{/*
Get redis secret name
*/}}
{{- define "motor.redisSecretName" -}}
{{- if .Values.global.redis.existingSecret }}
{{- .Values.global.redis.existingSecret }}
{{- else }}
{{- printf "%s-redis" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get sentry secret name
*/}}
{{- define "motor.sentrySecretName" -}}
{{- if .Values.global.sentry.existingSecret }}
{{- .Values.global.sentry.existingSecret }}
{{- else }}
{{- printf "%s-sentry" .Release.Name }}
{{- end }}
{{- end }}
