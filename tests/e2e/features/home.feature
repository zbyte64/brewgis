Feature: Home Page
  As a logged-in user
  I want to see my workspaces and navigation links
  So that I can manage my GIS data

  Background:
    Given the user is logged in

  @e2e
  Scenario: Authenticated user sees workspace list
    Given a workspace named "Test Workspace" exists
    When I navigate to the home page
    Then I should see "Test Workspace"
    And I should see a "View Map" link

  @e2e
  Scenario: No workspaces shows empty message
    When I navigate to the home page
    Then I should see "No Workspaces Yet"

  @e2e
  Scenario: Navigation links are visible
    When I navigate to the home page
    Then I should see a "Upload GIS File" heading
    And I should see a "Create Layer" heading
    And I should see a "Building Types" heading
    And I should see a "Place Types" heading
