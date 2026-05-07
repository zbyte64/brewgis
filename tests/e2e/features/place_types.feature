Feature: Place Types
  As a logged-in user
  I want to manage place types with ROW allocation and building type mixes
  So that I can model development scenarios

  Background:
    Given the user is logged in

  @e2e
  Scenario: Place types list shows empty state
    When I navigate to the place types page
    Then I should see "No place types yet"
    And I should see a "+ New Place Type" button

  @e2e
  Scenario: Create a place type
    When I navigate to the place types page
    And I click "+ New Place Type"
    Then I should see "New Place Type" in the page title
    And I should see a form with name and ROW allocation fields

  @e2e
  Scenario: Place types page requires authentication
    Given the user is not logged in
    When I navigate to the place types page
    Then I should be on the login page
