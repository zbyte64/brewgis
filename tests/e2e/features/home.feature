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
    Then I should see "No workspaces found"

  @e2e
  Scenario: Navigation links are visible
    When I navigate to the home page
    Then I should see "Upload GIS File"
    And I should see "Create Layer"
    And I should see "Building Types"
    And I should see "Place Types"
