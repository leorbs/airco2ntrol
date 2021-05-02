"""Example Load Platform integration."""
DOMAIN = 'airco2ntrol'

def setup(hass, config):
    """Your controller/hub specific code."""
    # Data that you want to share with your platforms
    hass.data[DOMAIN] = {
    }
    
    return True
