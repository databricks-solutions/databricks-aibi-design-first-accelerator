-- Sample MEASURE() queries for validated Member Claims metric views (v2)

-- 1. Overall financial and claim volume KPIs
SELECT
  MEASURE(total_claims) AS total_claims,
  MEASURE(total_claim_lines) AS total_claim_lines,
  MEASURE(total_paid_amount) AS total_paid_amount,
  MEASURE(average_paid_per_claim) AS average_paid_per_claim
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2;

-- 2. Paid amount and claims by service month
SELECT
  service_month,
  MEASURE(total_claims) AS total_claims,
  MEASURE(total_paid_amount) AS total_paid_amount
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY service_month
ORDER BY service_month;

-- 3. Claims and paid by claim type
SELECT
  claim_type,
  MEASURE(total_claims) AS total_claims,
  MEASURE(total_claim_lines) AS total_claim_lines,
  MEASURE(total_paid_amount) AS total_paid_amount
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY claim_type
ORDER BY total_paid_amount DESC;

-- 4. Denial rate and clean claim rate by adjudication status
SELECT
  adjudication_status,
  MEASURE(total_claim_lines) AS total_claim_lines,
  MEASURE(denied_lines) AS denied_lines,
  MEASURE(denial_rate) AS denial_rate,
  MEASURE(clean_claim_rate) AS clean_claim_rate
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY adjudication_status
ORDER BY total_claim_lines DESC;

-- 5. Payment ratios by line of business
SELECT
  line_of_business,
  MEASURE(total_paid_amount) AS total_paid_amount,
  MEASURE(total_billed_amount) AS total_billed_amount,
  MEASURE(total_allowed_amount) AS total_allowed_amount,
  MEASURE(payment_to_billed_ratio) AS payment_to_billed_ratio,
  MEASURE(payment_to_allowed_ratio) AS payment_to_allowed_ratio
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY line_of_business
ORDER BY total_paid_amount DESC;

-- 6. Claiming-member utilization measures by line of business
SELECT
  line_of_business,
  MEASURE(unique_members) AS unique_claiming_members,
  MEASURE(claims_per_member) AS claims_per_claiming_member,
  MEASURE(average_paid_per_member) AS average_paid_per_claiming_member
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY line_of_business
ORDER BY average_paid_per_claiming_member DESC;

-- 7. Lines per claim by benefit category
SELECT
  benefit_category,
  MEASURE(total_claims) AS total_claims,
  MEASURE(total_claim_lines) AS total_claim_lines,
  MEASURE(lines_per_claim) AS lines_per_claim
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY benefit_category
ORDER BY total_claim_lines DESC;

-- 8. Inpatient and outpatient paid amounts by service month
SELECT
  service_month,
  MEASURE(inpatient_paid_amount) AS inpatient_paid_amount,
  MEASURE(outpatient_paid_amount) AS outpatient_paid_amount,
  MEASURE(total_paid_amount) AS total_paid_amount
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY service_month
ORDER BY service_month;

-- 9. Participating provider rate by rendering provider specialty
SELECT
  rendering_provider_specialty,
  MEASURE(total_paid_amount) AS total_paid_amount,
  MEASURE(par_paid_amount) AS participating_provider_paid_amount,
  MEASURE(participating_provider_rate) AS participating_provider_rate
FROM aw_serverless_stable_catalog.aibi_member_claims.member_claims_metric_view_v2
GROUP BY rendering_provider_specialty
ORDER BY total_paid_amount DESC;

-- 10. Enrollment KPIs by line of business
SELECT
  enrollment_line_of_business,
  MEASURE(new_member_enrollment) AS new_member_enrollment,
  MEASURE(active_enrolled_members) AS active_enrolled_members
FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2
GROUP BY enrollment_line_of_business
ORDER BY active_enrolled_members DESC;

-- 11. Active enrolled members by geography
SELECT
  member_state,
  member_zip_code,
  MEASURE(active_enrolled_members) AS active_enrolled_members
FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2
GROUP BY member_state, member_zip_code
ORDER BY active_enrolled_members DESC;

-- 12. Enrollment trend by month
SELECT
  enrollment_month,
  MEASURE(new_member_enrollment) AS new_member_enrollment,
  MEASURE(active_enrolled_members) AS active_enrolled_members
FROM aw_serverless_stable_catalog.aibi_member_claims.member_enrollment_metric_view_v2
GROUP BY enrollment_month
ORDER BY enrollment_month;
