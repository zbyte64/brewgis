Feature: dbt-level workspace and scenario isolation
  As a platform engineer
  I want to verify that dbt models respect workspace and scenario isolation
  So that concurrent scenario runs do not interfere with each other

  Background:
    Given idle dbt connections are terminated
    And schema "public" exists

  @integration
  Scenario: Two scenarios produce independently-named output views
    Given a parcel table "bdd_parcels_scenario_names" exists in schema "public"
    When I run dbt module "env_constraint" with scenario_id "bdd_scenario_a" in schema "public"
    Then a view named "env_constraint_bdd_scenario_a" should exist in schema "public"
    When I run dbt module "env_constraint" with scenario_id "bdd_scenario_b" in schema "public"
    Then a view named "env_constraint_bdd_scenario_b" should exist in schema "public"

  @integration
  Scenario: Two target schemas isolate workspace data
    Given schema "ws_a" exists
    And schema "ws_b" does not exist
    And a parcel table "bdd_parcels_ws_isolation" exists in schema "public"
    When I run dbt module "env_constraint" with scenario_id "bdd_ws_test" in schema "ws_a"
    Then a view named "env_constraint_bdd_ws_test" should exist in schema "ws_a"
    And no view named "env_constraint_bdd_ws_test" should exist in schema "ws_b"

  @integration
  Scenario: Running a single model does not create unrelated models
    Given a parcel table "bdd_parcels_single_model" exists in schema "public"
    When I run dbt module "env_constraint" with scenario_id "bdd_single" in schema "public"
    Then a view named "env_constraint_bdd_single" should exist in schema "public"
    And no view named "end_state" should exist in schema "public"

  @integration
  Scenario: Re-running with the same scenario_id does not corrupt existing data
    Given a parcel table "bdd_parcels_idempotent" exists in schema "public"
    When I run dbt module "env_constraint" with scenario_id "bdd_idempotent" in schema "public"
    Then the dbt run should have succeeded
    And a view named "env_constraint_bdd_idempotent" should exist in schema "public"
    When I run dbt module "env_constraint" with scenario_id "bdd_idempotent" in schema "public" a second time
    Then the dbt run should have succeeded
    And a view named "env_constraint_bdd_idempotent" should exist in schema "public"
