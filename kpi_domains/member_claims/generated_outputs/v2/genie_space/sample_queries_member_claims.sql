-- Sample validated Genie SQL queries for member_claims
-- All queries use metric view MEASURE() syntax and exact backtick-quoted FQNs from step_handoff.yaml.

-- Q1: What are total claims, claim lines, and total paid amount?
SELECT MEASURE(`Total Claims`) AS total_claims, MEASURE(`Total Claim Lines`) AS total_claim_lines, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2`;

-- Q2: How has total paid amount trended by service month?
SELECT service_month, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY service_month;

-- Q3: Show denial rate by claim type.
SELECT claim_type, MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY denial_rate DESC;

-- Q4: What is the clean claim rate for Clean claim lines?
SELECT MEASURE(`Clean Claim Rate`) AS clean_claim_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` WHERE clean_claim_indicator = 'Clean';

-- Q5: Which benefit categories have the highest total paid amount?
SELECT benefit_category, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY total_paid_amount DESC LIMIT 10;

-- Q6: Compare payment-to-billed ratio across claim types.
SELECT claim_type, MEASURE(`Payment-to-Billed Ratio`) AS payment_to_billed_ratio FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY claim_type;

-- Q7: What percentage of claim lines are denied?
SELECT MEASURE(`Denial Rate`) AS denial_rate FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2`;

-- Q8: Show average paid per claim by line of business.
SELECT line_of_business, MEASURE(`Average Paid per Claim`) AS average_paid_per_claim FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY average_paid_per_claim DESC;

-- Q9: What are inpatient and outpatient paid amounts by service month?
SELECT service_month, MEASURE(`Inpatient Paid Amount`) AS inpatient_paid_amount, MEASURE(`Outpatient Paid Amount`) AS outpatient_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY service_month;

-- Q10: Which rendering provider specialties have the highest total paid amount?
SELECT rendering_provider_specialty, MEASURE(`Total Paid Amount`) AS total_paid_amount FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_metric_view_v2` GROUP BY ALL ORDER BY total_paid_amount DESC LIMIT 10;

-- Q11: How many active members are there by line of business?
SELECT line_of_business, MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v2` GROUP BY ALL ORDER BY active_members DESC;

-- Q12: Show active members by state.
SELECT state, MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v2` GROUP BY ALL ORDER BY active_members DESC;

-- Q13: How has new member enrollment changed by service month?
SELECT service_month, MEASURE(`New Member Enrollment`) AS new_member_enrollment FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v2` GROUP BY ALL ORDER BY service_month;

-- Q14: What are active members for Medicare enrollment?
SELECT MEASURE(`Active Members`) AS active_members FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v2` WHERE line_of_business = 'Medicare';

-- Q15: Compare enrollment records and member months by enrollment status.
SELECT enrollment_status, MEASURE(`Enrollment Records`) AS enrollment_records, MEASURE(`Member Months`) AS member_months FROM `aw_serverless_stable_catalog`.`aibi_member_claims`.`member_claims_enrollment_metric_view_v2` GROUP BY ALL ORDER BY enrollment_records DESC;
