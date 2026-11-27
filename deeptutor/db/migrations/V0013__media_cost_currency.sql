-- Phase 8: record what a job cost in money, not only in tokens.
--
-- Gate 8's cost column had a gap that took a provider to see: the ledger
-- recorded tokens and a Toman figure for non-token units, but never a dollar
-- amount for the tokens themselves. "1000 tokens" is not a cost; it becomes one
-- only when multiplied by a price, and that price lives at the provider.
--
-- Why micro-USD as an integer
-- ---------------------------
-- The endpoints for a single OpenRouter model span 6e-8 to 1.83e-6 USD per
-- token. Storing USD as REAL means storing a number whose meaningful digits sit
-- far below a cent, and a ledger that sums floats accumulates error in exactly
-- the place nobody looks. Integer micro-USD is 0.000001 USD: finer than any
-- price we have observed, and exact under addition.
--
-- Why NULL is not zero
-- --------------------
-- A free endpoint genuinely costs 0. An unpriced renderer genuinely costs
-- "unknown". Collapsing those two into one value is how a report ends up
-- claiming a cost it never measured, so the column is nullable and the
-- difference is preserved.

-- @@ UP @@

ALTER TABLE media_job_costs ADD COLUMN cost_microusd INTEGER;

-- The price used to compute it, as JSON: rates, unit, and which endpoint was
-- live. Prices change; a cost row whose rate is not recorded cannot be
-- audited later, only believed.
ALTER TABLE media_job_costs ADD COLUMN price_json TEXT NOT NULL DEFAULT '';

-- @@ DOWN @@

ALTER TABLE media_job_costs DROP COLUMN price_json;
ALTER TABLE media_job_costs DROP COLUMN cost_microusd;
