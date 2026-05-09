Feature: Basemap UX
  As a user customizing map appearance
  I want the basemap picker to show available basemaps
  So that I can choose a basemap style for my map

  Background:
    Given the user is logged in

  @review
  Scenario: Basemap picker renders available basemaps
    Given a basemap named "OpenStreetMap" exists
    When I navigate to the basemap picker
    Then I should see available basemap options

  @review
  Scenario: Basemap picker shows empty state
    When I navigate to the basemap picker
    Then I should see "No basemaps available"
