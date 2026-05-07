Feature: Building Types
  As a logged-in user
  I want to manage building types with density, energy, and water parameters
  So that I can define built form archetypes

  Background:
    Given the user is logged in

  @e2e
  Scenario: Building types list shows empty state
    When I navigate to the building types page
    Then I should see "No building types yet"
    And I should see a "+ New Building Type" button

  @e2e
  Scenario: Create a building type
    When I navigate to the building types page
    And I click "+ New Building Type"
    Then I should see "New Building Type" in the page title
    And I should see a form with name and density fields

  @e2e
  Scenario: Building types page requires authentication
    Given the user is not logged in
    When I navigate to the building types page
    Then I should be on the login page
