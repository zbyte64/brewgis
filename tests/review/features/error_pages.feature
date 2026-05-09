Feature: Error Pages UX
  As a user of the application
  I want to see friendly error pages when something goes wrong
  So that I understand what happened and what to do next

  Background:
    Given the user is logged in

  @review
  Scenario: 404 page shows friendly message
    When I navigate to a non-existent page
    Then I should see "Page not found"
    And the page title contains Page not found
    And the response status is 200
