Feature: Authentication
  As a user
  I want to sign in and sign out
  So that I can access protected features

  Background:
    Given the user is not logged in

  @e2e
  Scenario: Login with valid credentials
    When I navigate to the login page
    And I log in as "testuser" with password "testpass123"
    Then I should be on the home page
    And I should see "Sign Out" in the navigation

  @e2e
  Scenario: Login with invalid credentials
    When I navigate to the login page
    And I log in as "testuser" with password "wrongpassword"
    Then I should see an error message on the login page

  @e2e
  Scenario: Unauthenticated user is redirected to login
    When I navigate to the upload page
    Then I should be on the login page

  @e2e
  Scenario: Logout
    Given the user is logged in
    When I log out
    Then I should be on the home page
    And I should see "Sign In" in the navigation
