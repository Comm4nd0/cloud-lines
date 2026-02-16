"""
Centralised constants for the Cloud-Lines application.

These replace magic strings scattered throughout the codebase.
Import from here instead of using raw string literals.
"""


# --- Service tier names ---
class ServiceNames:
    FREE = 'Free'
    SMALL_SOCIETY = 'Small Society'
    LARGE_SOCIETY = 'Large Society'
    ORGANISATION = 'Organisation'

    # Tiers that get their own dedicated infrastructure
    LARGE_TIERS = (SMALL_SOCIETY, LARGE_SOCIETY, ORGANISATION)

    # Tiers with unlimited animals
    UNLIMITED_ANIMAL_TIERS = (LARGE_SOCIETY, ORGANISATION)


# --- Bolton (add-on) identifiers ---
class BoltonTypes:
    BIRTH_NOTIFICATION = '1'
    MEMBERSHIPS = '2'

    NAMES = {
        BIRTH_NOTIFICATION: 'Birth Notification',
        MEMBERSHIPS: 'Memberships',
    }


# --- Pedigree / BreedGroup / PedigreeImage states ---
class States:
    EDITED = 'edited'
    UNAPPROVED = 'unapproved'
    APPROVED = 'approved'

    CHOICES = (
        (EDITED, 'Edited'),
        (UNAPPROVED, 'Unapproved'),
        (APPROVED, 'Approved'),
    )


# --- Pedigree status (alive/dead) ---
class PedigreeStatus:
    DEAD = 'dead'
    ALIVE = 'alive'
    UNKNOWN = 'unknown'

    CHOICES = (
        (DEAD, 'Dead'),
        (ALIVE, 'Alive'),
        (UNKNOWN, 'Unknown'),
    )


# --- Pedigree sex/gender ---
class PedigreeSex:
    MALE = 'male'
    FEMALE = 'female'
    CASTRATED = 'castrated'
    UNKNOWN = 'unknown'

    CHOICES = (
        (MALE, 'Male'),
        (FEMALE, 'Female'),
        (CASTRATED, 'Castrated'),
        (UNKNOWN, 'Unknown'),
    )


# --- Birth notification child status ---
class BnChildStatus:
    DECEASED = 'deceased'
    ALIVE = 'alive'
    DIED_PRE_REG = 'died_pre_reg'

    CHOICES = (
        (DECEASED, 'Deceased'),
        (ALIVE, 'Alive'),
        (DIED_PRE_REG, 'Died Pre Reg'),
    )


# --- Site modes ---
class SiteModes:
    MAMMAL = 'mammal'
    POULTRY = 'poultry'

    CHOICES = (
        (MAMMAL, 'Mammal'),
        (POULTRY, 'Poultry'),
    )


# --- Permission levels (used in API membership endpoint) ---
class PermissionLevels:
    READ_ONLY = 'read_only_users'
    CONTRIBUTORS = 'contributors'
    ADMIN = 'admin_users'

    ALL = (READ_ONLY, CONTRIBUTORS, ADMIN)


# --- Default animal type ---
DEFAULT_ANIMAL_TYPE = 'Pedigrees'

# --- Build states for LargeTierQueue ---
class BuildStates:
    WAITING = 'waiting'
    BUILDING = 'building'
    COMPLETE = 'complete'

    CHOICES = (
        (WAITING, 'Waiting'),
        (BUILDING, 'Building'),
        (COMPLETE, 'Complete'),
    )
