{{/*
Expand the name of the chart.
*/}}
{{- define "pv-portal.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
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
Redis URL helper
*/}}
{{- define "pv-portal.redisUrl" -}}
{{- if .Values.redis.enabled }}
redis://{{ include "pv-portal.fullname" . }}-redis:6379/0
{{- else if .Values.redis.externalUrl }}
{{- .Values.redis.externalUrl }}
{{- else }}
redis://localhost:6379/0
{{- end }}
{{- end }}

{{/*
MinIO/S3 endpoint helper
*/}}
{{- define "pv-portal.s3Endpoint" -}}
{{- if .Values.minio.enabled }}
http://{{ include "pv-portal.fullname" . }}-minio:9000
{{- else if .Values.s3.externalEndpoint }}
{{- .Values.s3.externalEndpoint }}
{{- else }}
{{- end }}
{{- end }}

{{/*
PostgreSQL URL helper
*/}}
{{- define "pv-portal.postgresUrl" -}}
{{- if .Values.postgres.enabled }}
postgresql://{{ .Values.postgres.username }}:{{ .Values.postgres.password }}@{{ include "pv-portal.fullname" . }}-postgres:5432/{{ .Values.postgres.database }}
{{- else if .Values.postgres.externalUrl }}
{{- .Values.postgres.externalUrl }}
{{- else }}
{{- end }}
{{- end }}
