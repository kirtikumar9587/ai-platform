# Operations Runbook

## On-call escalation
The primary on-call engineer is paged first and must acknowledge within 5 minutes. If there is no acknowledgement
after 15 minutes the secondary on-call engineer is paged.

## Restarting payment-service
Step 1: drain traffic from the instance through the load balancer.
Step 2: restart the service and wait for the health check to pass.
Step 3: re-enable traffic gradually.

## Certificates
TLS certificates are currently renewed manually by the Platform team every 90 days.

## Backups
Database backups run daily at 02:00 UTC and are retained for 30 days.

## Support targets (legacy)
P1 incidents must receive a first response within 30 minutes.
