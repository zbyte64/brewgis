Feature: Data Catalog Populated State
  As a user viewing the workspace detail hub
  I want the data catalog to accurately show populated data
  So that I can understand what data is loaded in my workspace

  Background:
    Given the user is logged in
    And a workspace named "Test Region" exists

  @review
  Scenario: Data catalog shows category count badge
    Given the workspace has a data source category "Demographics"
    When I navigate to the workspace detail page
    Then the data catalog should show category count

  @review
  Scenario: Data catalog shows source details
    Given the workspace has a data source category "Demographics"
    And the workspace has a data source named "Census Tract" in category "Demographics"
    When I navigate to the workspace detail page
    Then the data catalog source "Census Tract" should be present
