{#
    Assert that net_fiscal_impact satisfies the accounting identity:

        net_fiscal_impact = property_tax_revenue + sales_tax_revenue - service_cost_total

    Returns any rows where the identity is violated beyond a small monetary
    tolerance to allow for floating-point accumulation.
#}

{% set tolerance = 0.01 %}

SELECT
    parcel_id,
    property_tax_revenue,
    sales_tax_revenue,
    service_cost_total,
    net_fiscal_impact,
    (property_tax_revenue + sales_tax_revenue - service_cost_total) AS computed_net_fiscal_impact,
    ABS(net_fiscal_impact - (property_tax_revenue + sales_tax_revenue - service_cost_total)) AS deviation
FROM {{ ref('fiscal_net_impact') }}
WHERE ABS(net_fiscal_impact - (property_tax_revenue + sales_tax_revenue - service_cost_total)) > {{ tolerance }}
