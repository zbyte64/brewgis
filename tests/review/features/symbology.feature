Feature: Symbology Editor UX
  As a user configuring layer styles
  I want the symbology editor to provide clear style controls
  So that I can customize map layer appearance

  Background:
    Given the user is logged in

  @review
  Scenario: Symbology editor shows form and type options
    Given a layer named "Parcels" exists in workspace "Symbology WS"
    When I navigate to the symbology editor for the "Parcels" layer
    Then I should see the symbology editor form
    And the symbology type selector should include "Single Symbol", "Categorical", "Graduated"
    And I should see color controls

  @review
  Scenario: Symbology editor has save and auto-generate buttons
    Given a layer named "Streets" exists in workspace "Symbology WS"
    When I navigate to the symbology editor for the "Streets" layer
    Then I should see a "Save Symbology" button
    And I should see an auto-generate button
