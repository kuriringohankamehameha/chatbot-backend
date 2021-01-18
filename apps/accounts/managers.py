from django.contrib.auth.base_user import BaseUserManager
from apps.permission.models import PermissionRouting
from apps.permission import permission_json
from decouple import config



class UserManager(BaseUserManager):
    use_in_migrations = True


    def permission_handler(self, user, role):

        class AssignePermissions:

            def __init__(self, routes, nav_routes, user):
                self.routes = routes
                self.nav_routes = nav_routes
                self.user = user

            def assign_permission(self):
                try:
                    permission_routing = PermissionRouting(user=self.user, routes=self.routes, 
                    nav_routes=self.nav_routes)
                    permission_routing.save()
                    return True
                except Exception as e:
                    print(e)
                    return False

        if role == 'AM':
            routing = permission_json.admin_permission
            nav_routing = permission_json.admin_nav
            assign_details = AssignePermissions(routes=routing, nav_routes=nav_routing, user=user)
            is_assigned = assign_details.assign_permission()
            return is_assigned
        elif role == 'AO':
            routing = permission_json.admin_operator_permission
            nav_routing = permission_json.admin_operator_nav
            assign_details = AssignePermissions(routes=routing, nav_routes=nav_routing, user=user)
            is_assigned = assign_details.assign_permission()
            return is_assigned
        elif role == 'SAO':
            routing = permission_json.super_admin_permission
            nav_routing = permission_json.super_admin_permission
            assign_details = AssignePermissions(routes=routing, nav_routes=nav_routing, user=user)
            is_assigned = assign_details.assign_permission()
            return is_assigned
        elif role == 'SA':
            routing = permission_json.super_admin_permission
            nav_routing = permission_json.super_admin_permission
            assign_details = AssignePermissions(routes=routing, nav_routes=nav_routing, user=user)
            is_assigned = assign_details.assign_permission()
            return is_assigned
        else:
            return False    


    def _create_user(self, email, password, **extra_fields):
        """
        Creates and saves a User with the given email and password.
        """
        if not email:
            raise ValueError('The given email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)


        if extra_fields['is_superuser'] == True:
            permission = self.permission_handler(user, 'SA')
        else:
            permission = self.permission_handler(user, extra_fields['role'])
        return user


    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_superuser', False)
        extra_fields.setdefault('acc_version', config('PROJECT_VERSION'))
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('role', 'SA')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)
