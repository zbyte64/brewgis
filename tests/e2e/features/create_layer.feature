Feature: Create Layer
  As a logged-in user
  I want to create map layers
  So that I can visualize geographic data

  Background:
    Given the user is logged in
    And a workspace named "Layer Test WS" exists

  @e2e
  Scenario: Create layer page shows the form
    When I navigate to the create layer page
    Then I should see "New Layer" in the page title

  @e2e
  Scenario: Submit invalid form shows errors
    When I navigate to the create layer page
    And I submit the form with empty fields
    Then I should see a validation error message

  @e2e
  Scenario: Create layer requires authentication
    Given the user is not logged in
    When I navigate to the create layer page
    Then I should be on the login page
