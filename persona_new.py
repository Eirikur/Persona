def user_says(text:str) -> None:
    speak_in_room()
    conversation_log(text)
    [persona.hears(text) for persona in room.personas]

def attribute_to(persona:Persona) -> str:
    "Puts persona's name into the string"
    pass

    
def persona_hears(self, text):
    if self.active:
        ### get the text to the persona
    else: # persona is just listening.
         ### use prompt injection
        f"You hear {text}, but you do not respond."

def say_to_user(text:str)-> bool:
    pass

# in room object
def persona_enters(self, persona) -> None:
    pass
    
