"""
`Employee.role` becomes a fixed enum, plus the approval audit trail.

`role` was an unconstrained CharField, so whatever anyone typed is in the
column. Choices are not a database constraint, which means the AlterField
below would happily leave "inventory manager" sitting in a column that now
claims to be an enum — invisible until a permission check silently fails to
match. `normalise_existing_roles` converts what it recognises and reports what
it does not.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Stored value -> itself, plus the human labels the old free-text field is
# most likely to contain.
ROLE_VALUES = [
    'ADMIN',
    'INVENTORY_MANAGER',
    'DISPATCH_MANAGER',
    'FINANCE_MANAGER',
    'ORDER_MANAGER',
    'MARKETING_MANAGER',
    'MONEY_COLLECTOR',
    'BINDING_MANAGER',
    'PRINTING_MANAGER',
]


def _normalise(raw: str) -> str | None:
    """"Inventory Manager", " inventory-manager " -> "INVENTORY_MANAGER"."""
    candidate = raw.strip().upper().replace(' ', '_').replace('-', '_')
    return candidate if candidate in ROLE_VALUES else None


def normalise_existing_roles(apps, schema_editor):
    Employee = apps.get_model('staff_auth', 'Employee')

    unrecognised = {}
    for employee in Employee.objects.exclude(role__isnull=True).exclude(role=''):
        mapped = _normalise(employee.role)
        if mapped == employee.role:
            continue
        if mapped is None:
            # Left in place rather than nulled: a wrong role is visible and
            # fixable, a silently emptied one is neither. It matches no
            # permission set, so it grants nothing.
            unrecognised[employee.role] = unrecognised.get(employee.role, 0) + 1
            continue
        Employee.objects.filter(pk=employee.pk).update(role=mapped)

    if unrecognised:
        print(
            "\n  Roles left as-is because they match no enum value: "
            + ", ".join(f"{value!r} ({count})" for value, count in unrecognised.items())
            + "\n  Reassign these from the admin; they currently grant nothing."
        )


def unnormalise_roles(apps, schema_editor):
    """Reverse to the human labels the dropdown used to show."""
    Employee = apps.get_model('staff_auth', 'Employee')
    for value in ROLE_VALUES:
        Employee.objects.filter(role=value).update(role=value.replace('_', ' ').title())


class Migration(migrations.Migration):

    dependencies = [
        ('staff_auth', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='whitelistedip',
            options={'verbose_name': 'Whitelisted IP'},
        ),
        migrations.AddField(
            model_name='employee',
            name='approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='employee',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_employees', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='employee',
            name='registered_ip',
            field=models.GenericIPAddressField(blank=True, help_text='Client IP captured at signup, for auditing the approval.', null=True),
        ),
        migrations.AlterField(
            model_name='employee',
            name='role',
            field=models.CharField(blank=True, choices=[('ADMIN', 'Admin'), ('INVENTORY_MANAGER', 'Inventory Manager'), ('DISPATCH_MANAGER', 'Dispatch Manager'), ('FINANCE_MANAGER', 'Finance Manager'), ('ORDER_MANAGER', 'Order Manager'), ('MARKETING_MANAGER', 'Marketing Manager'), ('MONEY_COLLECTOR', 'Money Collector'), ('BINDING_MANAGER', 'Binding Manager'), ('PRINTING_MANAGER', 'Printing Manager')], db_index=True, help_text='Drives the permission matrix. Null until an admin assigns one.', max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name='employee',
            name='status',
            field=models.CharField(choices=[('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')], db_index=True, default='Pending', max_length=20),
        ),
        migrations.RunPython(normalise_existing_roles, unnormalise_roles),
    ]
