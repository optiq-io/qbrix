{{/*
Expand the name of the chart.
*/}}
{{- define "proxy.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "proxy.fullname" -}}
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
{{- define "proxy.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "proxy.labels" -}}
helm.sh/chart: {{ include "proxy.chart" . }}
{{ include "proxy.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: qbrix
app.kubernetes.io/component: proxy
{{- end }}

{{/*
Selector labels
*/}}
{{- define "proxy.selectorLabels" -}}
app.kubernetes.io/name: {{ include "proxy.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "proxy.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "proxy.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Resolved image tag; also used as the sentry release identifier
*/}}
{{- define "proxy.imageTag" -}}
{{- .Values.image.tag | default .Values.global.imageTag | default .Chart.AppVersion }}
{{- end }}

{{/*
Get the image repository with optional global registry
*/}}
{{- define "proxy.image" -}}
{{- $registry := .Values.global.imageRegistry | default "" }}
{{- $repository := .Values.image.repository }}
{{- $tag := include "proxy.imageTag" . }}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- else }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}

{{/*
Get motor service host
*/}}
{{- define "proxy.motorHost" -}}
{{- if .Values.config.motor.host }}
{{- .Values.config.motor.host }}
{{- else }}
{{- printf "%s-motor" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get cortex service host
*/}}
{{- define "proxy.cortexHost" -}}
{{- if .Values.config.cortex.host }}
{{- .Values.config.cortex.host }}
{{- else }}
{{- printf "%s-cortex" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get postgres host
*/}}
{{- define "proxy.postgresHost" -}}
{{- .Values.global.postgres.host | default (printf "%s-postgres" .Release.Name) }}
{{- end }}

{{/*
Get redis host
*/}}
{{- define "proxy.redisHost" -}}
{{- .Values.global.redis.host | default (printf "%s-redis" .Release.Name) }}
{{- end }}

{{/*
Get clickhouse host
*/}}
{{- define "proxy.clickhouseHost" -}}
{{- .Values.global.clickhouse.host | default (printf "%s-clickhouse" .Release.Name) }}
{{- end }}

{{/*
Get clickhouse secret name
*/}}
{{- define "proxy.clickhouseSecretName" -}}
{{- if .Values.global.clickhouse.existingSecret }}
{{- .Values.global.clickhouse.existingSecret }}
{{- else }}
{{- printf "%s-clickhouse" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get postgres secret name
*/}}
{{- define "proxy.postgresSecretName" -}}
{{- if .Values.global.postgres.existingSecret }}
{{- .Values.global.postgres.existingSecret }}
{{- else }}
{{- printf "%s-postgres" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Get redis secret name
*/}}
{{- define "proxy.redisSecretName" -}}
{{- if .Values.global.redis.existingSecret }}
{{- .Values.global.redis.existingSecret }}
{{- else }}
{{- printf "%s-redis" .Release.Name }}
{{- end }}
{{- end }}

{{/*
Public console url: explicit config, else the ingress host the api is served on
*/}}
{{- define "proxy.consoleUrl" -}}
{{- if or .Values.config.consoleUrl .Values.config.cloudUrl }}
{{- .Values.config.consoleUrl | default .Values.config.cloudUrl }}
{{- else if and .Values.ingress.enabled .Values.ingress.hosts }}
{{- printf "%s://%s" (ternary "https" "http" (gt (len .Values.ingress.tls) 0)) (first .Values.ingress.hosts).host }}
{{- end }}
{{- end }}

{{/*
Get JWT secret name
*/}}
{{- define "proxy.jwtSecretName" -}}
{{- if .Values.config.jwt.existingSecret }}
{{- .Values.config.jwt.existingSecret }}
{{- else }}
{{- printf "%s-jwt" (include "proxy.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Get token secret name
*/}}
{{- define "proxy.tokenSecretName" -}}
{{- if .Values.config.token.existingSecret }}
{{- .Values.config.token.existingSecret }}
{{- else }}
{{- printf "%s-token" (include "proxy.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Get sentry secret name
*/}}
{{- define "proxy.sentrySecretName" -}}
{{- if .Values.global.sentry.existingSecret }}
{{- .Values.global.sentry.existingSecret }}
{{- else }}
{{- printf "%s-sentry" .Release.Name }}
{{- end }}
{{- end }}
