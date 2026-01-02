# BESS SLO Incident Runbooks

Version: v3.9.0

## Overview

This document provides step-by-step procedures for responding to SLO-related incidents.

## Quick Reference

| Alert | Severity | Action |
|-------|----------|--------|
| BESSAvailabilitySLOFastBurn | critical | Immediate investigation |
| BESSAvailabilitySLOMediumBurn | warning | Investigate within 1 hour |
| BESSAvailabilitySLOSlowBurn | warning | Investigate within 4 hours |
| BESSAvailabilityBudgetExhausted | critical | Feature freeze, all hands |
| BESSLatencySLOBreach | warning | Check resources and queries |
| BESSLatencySLOSustained | critical | Escalate to on-call |

---

## Runbook: BESSAvailabilitySLOFastBurn

### Description
Error budget is being consumed at 14.4x the sustainable rate. At this rate, the 30-day budget will be exhausted in ~2 days.

### Severity
**Critical** - Requires immediate response

### Investigation Steps

1. **Check error rates**
   ```promql
   # Current error rate
   sum(rate(http_requests_total{job="bess-dispatch", status=~"5.."}[5m]))
   /
   sum(rate(http_requests_total{job="bess-dispatch"}[5m]))

   # Error breakdown by status code
   sum by (status) (rate(http_requests_total{job="bess-dispatch", status=~"5.."}[5m]))
   ```

2. **Check pod health**
   ```bash
   kubectl get pods -n bess -l app=bess-dispatch
   kubectl describe pods -n bess -l app=bess-dispatch
   ```

3. **Check logs for errors**
   ```bash
   kubectl logs -n bess -l app=bess-dispatch --tail=100 | grep -i error
   ```

4. **Check external dependencies**
   ```promql
   # HA dependency status
   bess_ha_dependency_checks_total{result="unavailable"}
   ```

### Common Causes

| Cause | Symptoms | Resolution |
|-------|----------|------------|
| Pod crash loop | CrashLoopBackOff in kubectl | Check logs, fix app bug |
| Database unavailable | Connection errors in logs | Check DB status, failover |
| Redis unavailable | Cache errors in logs | Check Redis, restart if needed |
| OOM kills | OOMKilled in pod events | Increase memory limits |
| Recent deployment | Errors started after deploy | Rollback deployment |

### Mitigation

1. **If recent deployment**:
   ```bash
   kubectl rollout undo deployment/bess-dispatch -n bess
   ```

2. **If pod crashloop**:
   ```bash
   kubectl delete pod <pod-name> -n bess
   # Check if new pod is healthy
   ```

3. **If external dependency**:
   - Switch to HA_MODE=permissive temporarily
   - Failover to backup dependency

### Escalation

If not resolved within 15 minutes:
- Page on-call lead
- Start incident channel
- Consider partial service degradation

---

## Runbook: BESSAvailabilityBudgetExhausted

### Description
The 30-day availability error budget has been completely consumed.

### Severity
**Critical** - Requires immediate action and possible feature freeze

### Immediate Actions

1. **Declare incident**
   - Create incident in incident management system
   - Notify stakeholders

2. **Assess current state**
   ```promql
   # Current availability
   bess:sli:availability:ratio30d

   # Budget remaining
   bess:error_budget:remaining_ratio
   ```

3. **Implement feature freeze**
   - Halt all non-critical deployments
   - Cancel scheduled maintenance
   - Focus all engineering on reliability

### Recovery Plan

1. **Short-term (0-24h)**
   - Identify and fix immediate issues
   - Increase monitoring frequency
   - Consider scaling up resources

2. **Medium-term (1-7 days)**
   - Root cause analysis
   - Implement fixes for recurring issues
   - Add chaos tests for failure scenarios

3. **Long-term (7-30 days)**
   - Architecture improvements
   - Better alerting thresholds
   - Budget recovery tracking

### Budget Recovery

```promql
# Track recovery rate
# Should show budget increasing over time
bess:error_budget:remaining_ratio
```

Estimated recovery time:
- With 100% availability: ~0.5 days per 1% budget recovered
- With 99.9% availability: ~3 days per 1% budget recovered

---

## Runbook: BESSLatencySLOBreach

### Description
The p95 latency has exceeded the 2-second SLO target.

### Severity
**Warning** - Investigate within 1 hour

### Investigation Steps

1. **Check current latency**
   ```promql
   # Current p95 latency
   bess:sli:latency:p95_5m

   # Latency by endpoint
   bess:endpoint:latency:p95_5m
   ```

2. **Identify slow endpoints**
   ```promql
   # Endpoints exceeding 2s p95
   bess:endpoint:latency:p95_5m > 2
   ```

3. **Check CPU/memory pressure**
   ```promql
   # Container CPU usage
   sum(rate(container_cpu_usage_seconds_total{pod=~"bess-dispatch.*"}[5m])) by (pod)

   # Container memory usage
   sum(container_memory_usage_bytes{pod=~"bess-dispatch.*"}) by (pod)
   ```

4. **Check request rates**
   ```promql
   # Request rate trend
   sum(rate(http_requests_total{job="bess-dispatch"}[5m]))
   ```

### Common Causes

| Cause | Symptoms | Resolution |
|-------|----------|------------|
| High load | Increased request rate | Scale up replicas |
| Slow queries | DB latency high | Optimize queries, add indexes |
| Resource exhaustion | High CPU/memory | Increase limits |
| Cold cache | High cache miss rate | Warm up cache |
| Large responses | High network latency | Pagination, compression |

### Mitigation

1. **If high load**:
   ```bash
   kubectl scale deployment/bess-dispatch -n bess --replicas=5
   ```

2. **If slow queries**:
   - Check database query logs
   - Add caching for frequent queries
   - Consider read replicas

3. **If resource exhaustion**:
   ```bash
   kubectl patch deployment/bess-dispatch -n bess -p \
     '{"spec":{"template":{"spec":{"containers":[{"name":"bess-dispatch","resources":{"limits":{"cpu":"1000m","memory":"1Gi"}}}]}}}}'
   ```

---

## Runbook: HA Dependency Failure

### Description
External dependency (Redis/S3/Database) is unavailable.

### For HA_MODE=strict

All requests to affected functionality will fail with 503.

### Investigation Steps

1. **Identify failed dependency**
   ```promql
   bess_ha_request_rejected_total
   ```

2. **Check dependency health**

   **Redis**:
   ```bash
   kubectl exec -it redis-0 -n bess -- redis-cli ping
   ```

   **Database**:
   ```bash
   kubectl exec -it postgres-0 -n bess -- pg_isready
   ```

3. **Check recent changes**
   - Network policies
   - Firewall rules
   - Secret rotations

### Mitigation

1. **Temporary: Switch to permissive mode**
   ```bash
   kubectl set env deployment/bess-dispatch -n bess HA_MODE=permissive
   ```
   Note: This allows fallback but may cause data inconsistency.

2. **Restore dependency**
   - Restart dependency pods
   - Failover to replica
   - Restore from backup

3. **Return to strict mode**
   ```bash
   kubectl set env deployment/bess-dispatch -n bess HA_MODE=strict
   ```

---

## Escalation Matrix

| Time Since Alert | Action |
|------------------|--------|
| 0-15 min | Primary on-call investigates |
| 15-30 min | Page secondary on-call |
| 30-60 min | Page engineering lead |
| 1+ hour | Page VP Engineering, executive notification |

## Post-Incident

After every SLO-impacting incident:

1. **Document timeline** in incident system
2. **Write postmortem** within 48 hours
3. **Create action items** for prevention
4. **Update runbooks** with learnings
5. **Share with team** in weekly review

## Related Resources

- [SLO.md](../SLO.md) - SLO definitions and error budget policy
- [HA.md](../HA.md) - HA configuration guide
- [ALERTS.md](../observability/ALERTS.md) - All alerting rules
