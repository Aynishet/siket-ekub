# wsgi.py - For PythonAnywhere deployment
import sys
import os

# Add project directory to path
project_home = '/home/aynishet/siket-ekub'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# ===== ENVIRONMENT VARIABLES =====
os.environ['BOT_TOKEN'] = '8638438550:AAHR1TdyMjAhpRNq4ll0QMds6JZMVPZWock'
os.environ['ADMIN_IDS'] = '699428281'
os.environ['WEBAPP_URL'] = 'https://aynishet.pythonanywhere.com'
os.environ['SUPPORT_CHANNEL_LINK'] = 'https://t.me/siketekub'
os.environ['SUPPORT_CHANNEL_ID'] = '@siketekub'
os.environ['TICKET_CHANNEL_LINK'] = 'https://t.me/siketekubtiketo'
os.environ['TICKET_CHANNEL_ID'] = '@siketekubtiketo'

from dashboard_server import application