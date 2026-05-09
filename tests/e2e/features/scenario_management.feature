Feature: Scenario Management
  As a logged-in user
  I want to create and manage scenarios
  So that I can configure different analysis scenarios for my workspace

  Background:
    Given the user is logged in

  @e2e
  Scenario: Create scenario page shows form
    Given a workspace named "Scenario WS" exists
    When I navigate to the create scenario page for that workspace
    Then Create Scenario in the page title

  @e2e
  Scenario: Workspace detail page loads
    Given a workspace named "Scenario WS Detail" exists
    When I navigate to that workspace detail page
    Then I should see the workspace name in the page heading
