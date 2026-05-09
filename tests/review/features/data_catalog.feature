Feature: Data Catalog UX
  As a user viewing the workspace detail hub
  I want the data catalog to accurately reflect data availability
  So that I can understand what data is loaded in my workspace

  Background:
    Given the user is logged in

  @review
  Scenario: Data catalog shows empty state with import CTA
    Given a workspace named "Test Region" exists
    When I navigate to the workspace detail page
    Then the Data Catalog should show empty state
    And the Data Catalog should have an import data link

  @review
  Scenario: Data catalog shows empty state for workspaces without data
    Given a workspace named "Catalog Test" exists
    When I navigate to the workspace detail page
    Then the Data Catalog should show empty state

  @review
  Scenario: Quick action bar is present on workspace detail
    Given a workspace named "Actions WS" exists
    When I navigate to the workspace detail page
    Then I should see a quick-action bar with "View Map", "Import Data", "Run Analysis"

  @review
  Scenario: Workspace detail shows region header
    Given a workspace named "Detail Test" exists
    When I navigate to the workspace detail page
    Then the workspace name appears in the page heading
    And I should see the workspace name in the page header
