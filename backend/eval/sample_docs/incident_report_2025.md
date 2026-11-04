# Annual Incident Report 2025

## Summary
In 2025 the platform had 12 production incidents. Root causes by frequency:
1. Database connection pool exhaustion (orders-api): 5 incidents, 42% of all failures. Average recovery time 38 minutes.
2. Memory leak in payment-service v2.3: 3 incidents, 25% of failures. Average recovery time 55 minutes.
3. Expired TLS certificates (web-gateway): 2 incidents, 17% of failures. Average recovery time 22 minutes.
4. Misconfigured deployment (search-service): 2 incidents, 17% of failures. Average recovery time 31 minutes.

## Recommendations
- Database pool exhaustion: raise the connection pool size from 20 to 50 and add pgbouncer connection pooling.
- Memory leak: add heap profiling to the CI pipeline and upgrade payment-service beyond v2.3.
- TLS expiry: introduce automated certificate renewal and an alert 30 days before expiry.
- Bad deployments: adopt canary deployments with automatic rollback.
