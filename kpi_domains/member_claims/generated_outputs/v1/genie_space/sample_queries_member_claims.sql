-- Sample Genie example SQL queries for member_claims_analytics_genie_v1
-- All queries use validated Metric View measures via MEASURE() syntax.

-- 1
SELECT MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Claim Lines`) AS total_claim_lines, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`;

-- 2
SELECT `Service Month`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Service Month`;

-- 3
SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount, MEASURE(`Total Billed Amount`) AS total_billed_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC;

-- 4
SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` = 'Professional' AND `Service Date` >= DATE '2024-01-01' AND `Service Date` <= DATE '2024-12-31';

-- 5
SELECT `Benefit Category`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_paid_amount DESC;

-- 6
SELECT `Claim Type`, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Claim Type` IN ('Institutional', 'Professional') GROUP BY ALL ORDER BY `Claim Type`;

-- 7
SELECT `Benefit Level`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Unique Members With Claims`) AS unique_members_with_claims, MEASURE(`Claims per Member`) AS claims_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_claims DESC;

-- 8
SELECT `Claim Type`, MEASURE(`Payment-to-Billed Ratio`) AS payment_to_billed_ratio, MEASURE(`Payment-to-Allowed Ratio`) AS payment_to_allowed_ratio FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`;

-- 9
SELECT MEASURE(`Average Paid per Claim`) AS average_paid_per_claim FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`;

-- 10
SELECT `Service Month`, MEASURE(`Denial Rate`) AS denial_rate, MEASURE(`Clean Claim Rate`) AS clean_claim_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Service Date` >= DATE '2023-01-01' AND `Service Date` <= DATE '2023-12-31' GROUP BY ALL ORDER BY `Service Month`;

-- 11
SELECT `Line Status`, MEASURE(`Total Allowed Amount`) AS total_allowed_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_allowed_amount DESC;

-- 12
SELECT `Place of Service`, MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` WHERE `Benefit Category` = 'Inpatient' GROUP BY ALL ORDER BY total_paid_amount DESC;

-- 13
SELECT `Procedure Code`, MEASURE(`Total Claim Lines`) AS total_claim_lines FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY total_claim_lines DESC LIMIT 10;

-- 14
SELECT MEASURE(`Inpatient Paid Amount`) AS inpatient_paid_amount, MEASURE(`Outpatient Paid Amount`) AS outpatient_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1`;

-- 15
SELECT `Claim Type`, MEASURE(`Lines per Claim`) AS lines_per_claim, MEASURE(`Average Paid per Member`) AS average_paid_per_member FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v1` GROUP BY ALL ORDER BY `Claim Type`;
