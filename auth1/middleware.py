import uuid
from django.utils.deprecation import MiddlewareMixin


class GuestSessionMiddleware(MiddlewareMixin):
    """
    Assigns a unique guest_session_id to users who are not logged in.
    This is used to track guest invoice uploads without creating user accounts.
    """
    
    def process_request(self, request):
        # If user is already logged in, no guest session needed
        if request.session.get('username'):
            return None
        
        # If guest_session_id already exists in session, keep using it
        if request.session.get('guest_session_id'):
            return None
        
        # Assign new guest_session_id
        request.session['guest_session_id'] = str(uuid.uuid4())
        request.session['is_guest'] = True
        
        return None
