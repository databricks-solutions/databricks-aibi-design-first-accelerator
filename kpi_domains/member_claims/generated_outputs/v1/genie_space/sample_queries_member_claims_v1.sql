-- Sample MEASURE() queries for Member Claims Analytics
-- Genie Space: member_claims_analytics_genie_v1
-- Primary MV: aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1
-- Enrollment MV: aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1

-- Q1: What is total paid amount?
SELECT MEASURE(total_paid_amount) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q2: How many total claims?
SELECT MEASURE(total_claims) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q3: What is the denial rate?
SELECT MEASURE(denial_rate) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q4: Show paid amount by claim type
SELECT claim_type, MEASURE(total_paid_amount) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL;

-- Q5: What is the clean claim rate?
SELECT MEASURE(clean_claim_rate) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q6: Monthly paid amount trend
SELECT DATE_TRUNC('MONTH', service_date) AS service_month, MEASURE(total_paid_amount) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL ORDER BY service_month;

-- Q7: Top provider types by paid amount
SELECT rendering_provider_type, MEASURE(total_paid_amount) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL ORDER BY MEASURE(total_paid_amount) DESC;

-- Q8: Average paid per claim
SELECT MEASURE(avg_paid_per_claim) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q9: Unique members with claims
SELECT MEASURE(unique_members) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q10: Denial rate by claim type
SELECT claim_type, MEASURE(denial_rate) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL;

-- Q11: Payment to billed ratio
SELECT MEASURE(payment_to_billed_ratio) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q12: Denied lines by adjudication status
SELECT adjudication_status, MEASURE(denied_lines) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL;

-- Q13: Total deductible and copay
SELECT MEASURE(total_deductible), MEASURE(total_copay), MEASURE(total_coinsurance) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q14: Active enrolled members
SELECT MEASURE(active_members) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1;

-- Q15: Enrollment by insurance code
SELECT insured_code, MEASURE(active_members) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_enrollment_metric_view_v1 GROUP BY ALL;

-- Q16: Lines per claim
SELECT MEASURE(lines_per_claim) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1;

-- Q17: Claims and paid by line status
SELECT line_status, MEASURE(total_claims), MEASURE(total_paid_amount) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL;

-- Q18: Clean claims by provider type
SELECT rendering_provider_type, MEASURE(clean_claim_rate) FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v1 GROUP BY ALL;

