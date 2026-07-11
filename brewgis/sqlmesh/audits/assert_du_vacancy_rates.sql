AUDIT (
  name assert_du_vacancy_rates,
  dialect postgres
);
-- Vacancy rate is flat 0.05 for all parcels (regressor-based estimation)
SELECT
  apn,
  vacancy_rate
FROM @this_model
WHERE ABS(vacancy_rate - 0.05) > 0.001;
