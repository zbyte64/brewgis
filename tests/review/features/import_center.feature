Feature: Import Center UX
  As a user importing data into my workspace
  I want the import center to clearly organize import options
  So that I can find and use the right import method

  Background:
    Given the user is logged in

  @review
  Scenario: Import center shows all import tabs
    When I navigate to the import center
    Then I should see import tabs "Upload File", "Points of Interest", "Census Data", "Stitch & Fill"
    And the page title should be "Import Data"

  @review
  Scenario: Import center has breadcrumb navigation
    When I navigate to the import center
    Then I should see a breadcrumb
    And the breadcrumb should show "Home", "Import Data"

  @review
  Scenario: Upload File tab shows upload link
    When I navigate to the import center
    Then the "Upload File" tab should contain "Upload GIS File"
    And the "Upload File" tab should have an "Upload File" link

  @review
  Scenario: Census Data tab has sub-tabs
    When I navigate to the import center
    Then the "Census Data" tab should have sub-tabs "ACS Demographics", "LEHD Employment"
