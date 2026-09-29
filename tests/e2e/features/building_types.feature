Feature: Building Types
  As a logged-in user
  I want to manage building types with density, energy, and water parameters
  So that I can define built form archetypes

  Background:
    Given the user is logged in
    And a workspace named "Building Types WS" exists

  @e2e
  Scenario: Building types panel shows empty state
    When I navigate to the building types page
    Then I should see "No building types yet"
    And the built form panel should offer a new building type

  @e2e
  Scenario: Create a building type
    When I navigate to the building types page
    And I click the new building type button
    Then I should see a form with name and density fields

  @e2e
  Scenario: Building types panel requires authentication
    Given the user is not logged in
    When I navigate to the building types page
    Then I should be on the login page
