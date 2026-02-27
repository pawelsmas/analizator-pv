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
API component labels
*/}}
{{- define "pv-portal.api.labels" -}}
{{ include "pv-portal.labels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
API selector labels
*/}}
{{- define "pv-portal.api.selectorLabels" -}}
{{ include "pv-portal.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Worker component labels
*/}}
{{- define "pv-portal.worker.labels" -}}
{{ include "pv-portal.labels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "pv-portal.worker.selectorLabels" -}}
{{ include "pv-portal.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Frontend component labels
*/}}
{{- define "pv-portal.frontend.labels" -}}
{{ include "pv-portal.labels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Frontend selector labels
*/}}
{{- define "pv-portal.frontend.selectorLabels" -}}
{{ include "pv-portal.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Image tag helper
*/}}
{{- define "pv-portal.imageTag" -}}
{{- .tag | default $.Chart.AppVersion }}
{{- end }}

{{/*
==============================================================================
HA MODE GUARDRAIL
==============================================================================
This guardrail validates that HA mode is properly configured.

When ha.enabled=true OR any service has replicaCount > 1:
- postgresql.enabled must be true OR postgresql.external.host must be set
- redis.enabled must be true OR redis.external.host must be set
- runstore.backend must be "db"

If ha.strict=true (default), the chart will FAIL to deploy if these
requirements are not met. This prevents misconfigured HA deployments.
==============================================================================
*/}}
{{- define "pv-portal.ha.validate" -}}
{{- $haEnabled := .Values.ha.enabled }}
{{- $apiReplicas := .Values.api.replicaCount | int }}
{{- $workerReplicas := .Values.worker.replicaCount | int }}
{{- $needsHA := or $haEnabled (gt $apiReplicas 1) (gt $workerReplicas 1) }}

{{- if $needsHA }}
  {{- $errors := list }}

  {{/* Check PostgreSQL configuration */}}
  {{- $hasPostgres := or .Values.postgresql.enabled (and .Values.postgresql.external .Values.postgresql.external.host) }}
  {{- if not $hasPostgres }}
    {{- $errors = append $errors "HA mode requires PostgreSQL. Set postgresql.enabled=true or configure postgresql.external.host" }}
  {{- end }}

  {{/* Check Redis configuration */}}
  {{- $hasRedis := or .Values.redis.enabled (and .Values.redis.external .Values.redis.external.host) }}
  {{- if not $hasRedis }}
    {{- $errors = append $errors "HA mode requires Redis. Set redis.enabled=true or configure redis.external.host" }}
  {{- end }}

  {{/* Check runstore backend */}}
  {{- if ne .Values.runstore.backend "db" }}
    {{- $errors = append $errors "HA mode requires runstore.backend=db for shared state storage" }}
  {{- end }}

  {{/* Report errors */}}
  {{- if $errors }}
    {{- if .Values.ha.strict }}
      {{- fail (printf "\n\n========================================\nHA MODE CONFIGURATION ERROR\n========================================\n\nYou have configured HA mode (api.replicaCount=%d, worker.replicaCount=%d, ha.enabled=%t)\nbut the following requirements are NOT met:\n\n%s\n\nTo fix:\n1. Configure PostgreSQL and Redis (bundled or external)\n2. Set runstore.backend=db\n3. Or set ha.strict=false to disable this check (NOT recommended)\n\n========================================\n" $apiReplicas $workerReplicas $haEnabled (join "\n- " $errors)) }}
    {{- else }}
      {{- printf "\n# WARNING: HA mode misconfigured:\n# %s\n" (join "\n# " $errors) }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
PostgreSQL host helper
Returns bundled or external PostgreSQL host
*/}}
{{- define "pv-portal.postgresql.host" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "%s-postgresql" (include "pv-portal.fullname" .) }}
{{- else if .Values.postgresql.external.host }}
{{- .Values.postgresql.external.host }}
{{- else }}
{{- fail "PostgreSQL host not configured. Set postgresql.enabled=true or postgresql.external.host" }}
{{- end }}
{{- end }}

{{/*
PostgreSQL port helper
*/}}
{{- define "pv-portal.postgresql.port" -}}
{{- if .Values.postgresql.enabled }}
{{- 5432 }}
{{- else }}
{{- .Values.postgresql.external.port | default 5432 }}
{{- end }}
{{- end }}

{{/*
PostgreSQL database helper
*/}}
{{- define "pv-portal.postgresql.database" -}}
{{- if .Values.postgresql.enabled }}
{{- .Values.postgresql.auth.database | default "pvportal" }}
{{- else }}
{{- .Values.postgresql.external.database | default "pvportal" }}
{{- end }}
{{- end }}

{{/*
PostgreSQL secret name helper
*/}}
{{- define "pv-portal.postgresql.secretName" -}}
{{- if .Values.postgresql.enabled }}
  {{- if .Values.postgresql.auth.existingSecret }}
    {{- .Values.postgresql.auth.existingSecret }}
  {{- else }}
    {{- printf "%s-postgresql" (include "pv-portal.fullname" .) }}
  {{- end }}
{{- else if .Values.postgresql.external.existingSecret }}
  {{- .Values.postgresql.external.existingSecret }}
{{- else }}
  {{- printf "%s-postgresql-external" (include "pv-portal.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Redis host helper
Returns bundled or external Redis host
*/}}
{{- define "pv-portal.redis.host" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis-master" (include "pv-portal.fullname" .) }}
{{- else if .Values.redis.external.host }}
{{- .Values.redis.external.host }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{/*
Redis port helper
*/}}
{{- define "pv-portal.redis.port" -}}
{{- if .Values.redis.enabled }}
{{- 6379 }}
{{- else }}
{{- .Values.redis.external.port | default 6379 }}
{{- end }}
{{- end }}

{{/*
Redis secret name helper
*/}}
{{- define "pv-portal.redis.secretName" -}}
{{- if .Values.redis.enabled }}
  {{- if .Values.redis.auth.existingSecret }}
    {{- .Values.redis.auth.existingSecret }}
  {{- else }}
    {{- printf "%s-redis" (include "pv-portal.fullname" .) }}
  {{- end }}
{{- else if .Values.redis.external.existingSecret }}
  {{- .Values.redis.external.existingSecret }}
{{- end }}
{{- end }}

{{/*
MinIO/S3 endpoint helper
*/}}
{{- define "pv-portal.s3.endpoint" -}}
{{- if .Values.minio.enabled }}
{{- printf "http://%s-minio:9000" (include "pv-portal.fullname" .) }}
{{- else if .Values.minio.external.endpoint }}
{{- .Values.minio.external.endpoint }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{/*
MinIO/S3 bucket helper
*/}}
{{- define "pv-portal.s3.bucket" -}}
{{- if .Values.minio.enabled }}
{{- "pv-portal-artifacts" }}
{{- else }}
{{- .Values.minio.external.bucket | default "pv-portal-artifacts" }}
{{- end }}
{{- end }}

{{/*
Database URL helper
Constructs DATABASE_URL from components or uses direct value
*/}}
{{- define "pv-portal.databaseUrl" -}}
{{- if .Values.runstore.databaseUrl }}
{{- .Values.runstore.databaseUrl }}
{{- else if or .Values.postgresql.enabled .Values.postgresql.external.host }}
{{- $host := include "pv-portal.postgresql.host" . }}
{{- $port := include "pv-portal.postgresql.port" . }}
{{- $db := include "pv-portal.postgresql.database" . }}
{{- printf "postgresql://$(DB_USER):$(DB_PASSWORD)@%s:%s/%s" $host (toString $port) $db }}
{{- else }}
{{- "" }}
{{- end }}
{{- end }}

{{/*
RunStore backend configuration environment variables
*/}}
{{- define "pv-portal.runstore.env" -}}
- name: RUNSTORE_BACKEND
  value: {{ .Values.runstore.backend | quote }}
{{- if eq .Values.runstore.backend "db" }}
{{- if .Values.runstore.existingSecret }}
- name: RUNSTORE_DB_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Values.runstore.existingSecret }}
      key: {{ .Values.runstore.existingSecretKey | default "DATABASE_URL" }}
{{- else if .Values.runstore.databaseUrl }}
- name: RUNSTORE_DB_URL
  value: {{ .Values.runstore.databaseUrl | quote }}
{{- else if or .Values.postgresql.enabled .Values.postgresql.external.host }}
- name: DB_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "pv-portal.postgresql.secretName" . }}
      key: {{ if .Values.postgresql.enabled }}username{{ else }}{{ .Values.postgresql.external.existingSecretUserKey | default "username" }}{{ end }}
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "pv-portal.postgresql.secretName" . }}
      key: {{ if .Values.postgresql.enabled }}password{{ else }}{{ .Values.postgresql.external.existingSecretPasswordKey | default "password" }}{{ end }}
- name: RUNSTORE_DB_URL
  value: {{ include "pv-portal.databaseUrl" . | quote }}
{{- end }}
- name: RUNSTORE_DB_COMPRESS
  value: {{ .Values.runstore.compress | quote }}
{{- end }}
{{- end }}

{{/*
Redis configuration environment variables
*/}}
{{- define "pv-portal.redis.env" -}}
{{- $redisHost := include "pv-portal.redis.host" . }}
{{- if $redisHost }}
- name: REDIS_HOST
  value: {{ $redisHost | quote }}
- name: REDIS_PORT
  value: {{ include "pv-portal.redis.port" . | quote }}
{{- if or (and .Values.redis.enabled .Values.redis.auth.enabled) .Values.redis.external.existingSecret }}
- name: REDIS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "pv-portal.redis.secretName" . }}
      key: {{ if .Values.redis.enabled }}redis-password{{ else }}{{ .Values.redis.external.existingSecretKey | default "password" }}{{ end }}
{{- end }}
{{- end }}
{{- end }}

{{/*
S3/MinIO configuration environment variables
*/}}
{{- define "pv-portal.s3.env" -}}
{{- $s3Endpoint := include "pv-portal.s3.endpoint" . }}
{{- if $s3Endpoint }}
- name: S3_ENDPOINT
  value: {{ $s3Endpoint | quote }}
- name: S3_BUCKET
  value: {{ include "pv-portal.s3.bucket" . | quote }}
{{- if .Values.minio.enabled }}
- name: S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ if .Values.minio.auth.existingSecret }}{{ .Values.minio.auth.existingSecret }}{{ else }}{{ include "pv-portal.fullname" . }}-minio{{ end }}
      key: root-user
- name: S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ if .Values.minio.auth.existingSecret }}{{ .Values.minio.auth.existingSecret }}{{ else }}{{ include "pv-portal.fullname" . }}-minio{{ end }}
      key: root-password
{{- else if .Values.minio.external.existingSecret }}
- name: S3_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.minio.external.existingSecret }}
      key: {{ .Values.minio.external.existingSecretAccessKeyKey | default "access-key" }}
- name: S3_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.minio.external.existingSecret }}
      key: {{ .Values.minio.external.existingSecretSecretKeyKey | default "secret-key" }}
{{- else if .Values.minio.external.accessKey }}
- name: S3_ACCESS_KEY
  value: {{ .Values.minio.external.accessKey | quote }}
- name: S3_SECRET_KEY
  value: {{ .Values.minio.external.secretKey | quote }}
{{- end }}
- name: S3_REGION
  value: {{ .Values.minio.external.region | default "us-east-1" | quote }}
- name: S3_USE_SSL
  value: {{ if .Values.minio.enabled }}"false"{{ else }}{{ .Values.minio.external.useSSL | default "true" | quote }}{{ end }}
{{- end }}
{{- end }}
