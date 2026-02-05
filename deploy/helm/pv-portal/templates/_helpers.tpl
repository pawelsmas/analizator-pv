{{/*
Expand the name of the chart.
*/}}
{{- define "pv-portal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
*/}}
{{- define "pv-portal.fullname" -}}
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
{{- define "pv-portal.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "pv-portal.labels" -}}
helm.sh/chart: {{ include "pv-portal.chart" . }}
{{ include "pv-portal.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "pv-portal.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pv-portal.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API selector labels
*/}}
{{- define "pv-portal.api.selectorLabels" -}}
{{ include "pv-portal.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "pv-portal.worker.selectorLabels" -}}
{{ include "pv-portal.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "pv-portal.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "pv-portal.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Get the image tag
*/}}
{{- define "pv-portal.imageTag" -}}
{{- .Values.api.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Get the database URL
*/}}
{{- define "pv-portal.databaseUrl" -}}
{{- if .Values.database.external }}
{{- .Values.database.url }}
{{- else if .Values.database.embedded.enabled }}
{{- printf "postgresql://postgres:postgres@%s-postgres:5432/pvportal" (include "pv-portal.fullname" .) }}
{{- else }}
{{- .Values.database.url }}
{{- end }}
{{- end }}

{{/*
Get the Redis URL (if enabled)
*/}}
{{- define "pv-portal.redisUrl" -}}
{{- if .Values.redis.enabled }}
{{- if .Values.redis.embedded.enabled }}
{{- printf "redis://%s-redis:6379/0" (include "pv-portal.fullname" .) }}
{{- else }}
{{- .Values.redis.url }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Get artifact store backend
*/}}
{{- define "pv-portal.artifactStoreBackend" -}}
{{- .Values.artifactStore.backend | default "local" }}
{{- end }}
