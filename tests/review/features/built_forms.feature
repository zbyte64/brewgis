Feature: Built Forms UX
  As a user managing built forms
  I want building type and place type lists to be accessible
  So that I can configure land use definitions

  Background:
    Given the user is logged in

  @review
  Scenario: Building types page shows list
    Given a building type named "Single Family" exists
    When I navigate to the building types page
    Then I should see built form cards
    And I should see "Single Family" in the cards

  @review
  Scenario: Place types page shows list
    Given a place type named "Residential" exists
    When I navigate to the place types page
    Then I should see built form cards
    And I should see "Residential" in the cards

  @review
  Scenario: Bake button is accessible
    When I navigate to the building types page
    Then a bake button should be accessible
