Feature: Data Catalog UX
  As a user viewing the workspace detail hub
  I want the data catalog to accurately reflect data availability
  So that I can understand what data is loaded in my workspace

  Background:
    Given the user is logged in

  @review
  Scenario: Data catalog displays all configured source types
    Given a workspace named "Test Region" exists
    When I navigate to the workspace detail page
    Then the Data Catalog table should have 6 source rows
    And the Data Catalog should list "Census ACS"
    And the Data Catalog should list "LEHD Employment"
    And the Data Catalog should list "OSM Points of Interest"
    And the Data Catalog should list "Environmental Constraints"
    And the Data Catalog should list "Parcel Fabric"
    And the Data Catalog should list "County Boundary"

  @review
  Scenario: Data catalog table has expected columns
    Given a workspace named "Catalog Test" exists
    When I navigate to the workspace detail page
    Then the Data Catalog table should have columns "Source", "Description", "Status"
    And all sources should show status "Not Imported"

  @review
  Scenario: Quick action bar is present on workspace detail
    Given a workspace named "Actions WS" exists
    When I navigate to the workspace detail page
    Then I should see a quick-action bar with "View Map", "Import Data", "Run Analysis"

  @review
  Scenario: Workspace detail shows region header
    Given a workspace named "Detail Test" exists
    When I navigate to the workspace detail page
    Then I should see the workspace name in the page title
    And I should see the workspace name in the page header
