-- Sample Genie example SQL for member_claims. All queries validated successfully.
-- q01
SELECT MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Claim Lines`) AS total_claim_lines, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`;

-- q02
SELECT service_month, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY service_month;

-- q03
SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC;

-- q04
SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` = 'Institutional';

-- q05
SELECT `Benefit Category`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC LIMIT 5;

-- q06
SELECT `Claim Type`, MEASURE(`Clean Claim Rate`) AS clean_claim_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY clean_claim_rate DESC;

-- q07
SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`;

-- q08
SELECT `Claim Type`, MEASURE(`Payment-to-Billed Ratio`) AS payment_to_billed_ratio, MEASURE(`Payment-to-Allowed Ratio`) AS payment_to_allowed_ratio FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`;

-- q09
SELECT `Line of Business`, MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` GROUP BY ALL ORDER BY active_members DESC;

-- q10
SELECT MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` WHERE `Line of Business` = 'Commercial';

-- q11
SELECT `Member State`, MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` GROUP BY ALL ORDER BY active_members DESC;

-- q12
SELECT service_month, MEASURE(`New Member Enrollment`) AS new_member_enrollment FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v1` GROUP BY ALL ORDER BY service_month;

-- q13
SELECT `Line of Business`, MEASURE(`Average Paid per Member`) AS average_paid_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` GROUP BY ALL ORDER BY average_paid_per_member DESC;

-- q14
SELECT `Line of Business`, MEASURE(`Claims per Member`) AS claims_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` GROUP BY ALL ORDER BY claims_per_member DESC;

-- q15
SELECT MEASURE(`Participating Provider Rate`) AS participating_provider_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` WHERE `Line of Business` = 'Medicare Advantage';

-- q16
SELECT `Rendering Provider Specialty`, MEASURE(`Participating Provider Paid Amount`) AS participating_provider_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enriched_metric_view_v1` GROUP BY ALL ORDER BY participating_provider_paid_amount DESC LIMIT 5;
