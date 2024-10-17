import discord
from discord.ext import commands, tasks
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

intents = discord.Intents.default()
intents.members = True
intents.presences = True
intents.message_content = True  # Enable reading message content



bot = commands.Bot(command_prefix="!", intents=intents)

# Store events with roles and registered users
events = {}

# Define a template with roles
event_templates = {
    "PvE_Blue_Chest": ["Tank", "Healer", "M-DPS", "R-DPS", "DPS1", "DPS2", "DPS3"],
    "PvE_Golden_Chest": ["Tank", "Healer", "Ironroot", "Shadowcaller", "Blazing", "Perma", "BadonBow"],
    "Tracking_5P": ["Tank", "Healer", "R-DPS", "M-DPS", "DPS"],
    "Tracking_7P": ["Tank", "Healer", "R-DPS", "M-DPS", "DPS1", "DPS2", "DPS3"],
    "PVP_Small_Scall": ["D-Tank", "O-Tank", "Healer", "Catcher-DPS", "DPS1", "DPS2", "DPS3"],
    "Gathering Session": ["Gatherer1","Gatherer2","Gatherer3"],
    "Solo": ["solo"],


}

# Allowed channels for the bot
allowed_channels = [1296170170187907124]  # Replace with your actual channel IDs

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# New function to check if all roles are filled
async def check_all_roles_filled(event_name, channel):
    event = events[event_name]
    registered_users = [user for user in event["roles"].values() if user is not None]
    if all(user is not None for user in event["roles"].values()):
        await channel.send(f"✅ All positions for **{event_name}** are filled!")
        # Tag all registered users
        users_mention = ', '.join(user.mention for user in registered_users)
        # Create a scheduled Discord event when all roles are filled
        await create_discord_event(channel.guild, event_name, event["details"]["time"], event["details"]["description"], channel,users_mention)

# Function to create a Discord scheduled event
async def create_discord_event(guild, event_name, event_time, description, channel,users_mention):
    # Convert event_time (HH:MM) to a timezone-aware datetime object using UTC
    now = datetime.now(pytz.UTC)  # Current time in UTC
    event_time_obj = datetime.strptime(event_time, "%d/%m/%Y %H:%M %Z").time()  # Parse time only
    event_start_time = now.replace(hour=event_time_obj.hour, minute=event_time_obj.minute, second=0, microsecond=0)

    # Set event end time (example: 2 hours later)
    event_end_time = event_start_time + timedelta(hours=2)

    # Create the event in the guild (server)
    event = await guild.create_scheduled_event(
        name=event_name,
        start_time=event_start_time,
        end_time=event_end_time,
        description=description +"📢 Registered members:"+ users_mention,
        location=channel.mention,  # Event location can be set as the text channel
        entity_type=discord.EntityType.external,  # External event, happening outside a voice channel
                privacy_level=discord.PrivacyLevel.guild_only  # Restrict the event to guild members

    )

    # Notify users that the Discord event was created
    await channel.send(f"📅 **Discord Event Created:** [Click here to view the event](https://discord.com/events/{guild.id}/{event.id})")

# Modify the RoleButton callback to include a call to check_all_roles_filled
class RoleButton(discord.ui.Button):
    def __init__(self, role, event_name):
        super().__init__(label=role, style=discord.ButtonStyle.primary)
        self.role = role
        self.event_name = event_name

    async def callback(self, interaction: discord.Interaction):
        event = events[self.event_name]

        # Check if the user is already registered for any role
        already_registered = any(user == interaction.user for user in event["roles"].values())
        if already_registered:
            await interaction.response.send_message("You are already registered for a role in this event.", ephemeral=True)
            return

        # Check if the role is already taken
        if event["roles"][self.role] is not None:
            await interaction.response.send_message(f"Role {self.role} is already taken by {event['roles'][self.role].mention}.", ephemeral=True)
            return

        # Assign the user to the role
        event["roles"][self.role] = interaction.user

        # Disable the button after it's taken
        self.disabled = True

        # Update the event message
        event_message_id = event["message_id"]
        event_message = await interaction.channel.fetch_message(event_message_id)
        await event_message.edit(embed=build_event_embed(self.event_name), view=self.view)

        await interaction.response.send_message(f"✅ You've successfully registered as **{self.role}** for **{self.event_name}**!", ephemeral=True)

        # Check if all roles are filled and trigger Discord Event creation
        await check_all_roles_filled(self.event_name, interaction.channel)

# Make sure to handle the check when someone unregisters as well
class UnregisterButton(discord.ui.Button):
    def __init__(self, role, event_name, user):
        super().__init__(label=f"Unregister {role}", style=discord.ButtonStyle.danger)
        self.role = role
        self.event_name = event_name
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        event = events[self.event_name]

        # Check if the user is registered for this role
        if event["roles"][self.role] != self.user:
            await interaction.response.send_message("You are not registered for this role.", ephemeral=True)
            return

        # Unregister the user from this role
        event["roles"][self.role] = None
        await interaction.response.send_message(f"You've successfully unregistered from {self.role}.", ephemeral=True)

        # Update the event message
        event_message_id = event["message_id"]
        event_message = await interaction.channel.fetch_message(event_message_id)
        await event_message.edit(embed=build_event_embed(self.event_name), view=self.view)

        # You may want to notify users that someone unregistered
        await interaction.channel.send(f"⚠️ {interaction.user.mention} unregistered from **{self.role}** in **{self.event_name}**.")


class RoleSelectView(discord.ui.View):
    def __init__(self, event_name, user):
        super().__init__(timeout=None)
        self.event_name = event_name
        
        # Add a button for each role in the template
        for role in event_templates[event_name]:
            self.add_item(RoleButton(role, event_name))
            
            # Check if the user is already registered for this role
            if events[event_name]["roles"].get(role) == user:
                self.add_item(UnregisterButton(role, event_name, user))


# Command to create an event using command syntax
@bot.command()
async def create_event(ctx, event_name: str, event_date: str, event_time: str, mount_type: str, *, description: str):
    if event_name not in event_templates:
        await ctx.send("Event template not found.")
        return

    # Validate the event_date and event_time format (without timezone)
    try:
        event_datetime_str = f"{event_date} {event_time}"
        event_datetime_obj = datetime.strptime(event_datetime_str, "%d/%m/%Y %H:%M")  # Naive datetime

        # Make the datetime timezone-aware (set UTC explicitly or your local timezone)
        event_datetime_aware = pytz.UTC.localize(event_datetime_obj)  # Localize to UTC
        formatted_event_time = event_datetime_aware.strftime("%d/%m/%Y %H:%M %Z")  # Format with timezone info
    except ValueError:
        await ctx.send("Invalid date or time format. Please use the format: `DD/MM/YYYY HH:MM`.")
        return

    # Now you can safely use event_datetime_aware for scheduling Discord events or reminders
    await create_event_from_message(ctx.channel, event_name, formatted_event_time, mount_type, description)



@bot.command()
@commands.has_permissions(manage_messages=True)  # Ensure the user has permission to manage messages
async def clear(ctx, amount: int):
    # Check if the user provided a valid amount
    if amount <= 0:
        await ctx.send("❌ Please specify a valid number of messages to delete (greater than 0).")
        return
    
    # Try to delete the specified amount of messages
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"✅ Successfully deleted {len(deleted)} message(s).", delete_after=5)  # Message disappears after 5 seconds


@bot.command()
async def switch_role(ctx, event_name: str, new_role: str):
    # Check if the event exists
    if event_name not in events:
        await ctx.send("❌ Event not found. Please provide a valid event name.")
        return

    event = events[event_name]
    user = ctx.author

    # Check if the user is currently registered for any role
    current_role = None
    for role, registered_user in event["roles"].items():
        if registered_user == user:
            current_role = role
            break

    # If the user is not registered for any role
    if current_role is None:
        await ctx.send("❌ You are not registered for any role in this event.")
        return

    # Check if the new role is valid
    if new_role not in event["roles"]:
        await ctx.send(f"❌ `{new_role}` is not a valid role for this event.")
        return

    # Check if the new role is already taken
    if event["roles"][new_role] is not None:
        await ctx.send(f"❌ Role `{new_role}` is already taken by {event['roles'][new_role].mention}.")
        return

    # Switch the roles
    event["roles"][current_role] = None  # Unregister from current role
    event["roles"][new_role] = user  # Register to the new role

    # Update the event message to reflect the changes
    event_message_id = event["message_id"]
    event_message = await ctx.channel.fetch_message(event_message_id)
    await event_message.edit(embed=build_event_embed(event_name), view=RoleSelectView(event_name, ctx.guild.me))

    await ctx.send(f"✅ You've successfully switched from `{current_role}` to `{new_role}` for the event **{event_name}**!")

# Function to create an event from a message
async def create_event_from_message(channel, event_name, event_time, mount_type, description):
    # Initialize the event with roles and details
    events[event_name] = {
        "roles": {role: None for role in event_templates[event_name]},
        "details": {
            "time": event_time,
            "mount_type": mount_type,
            "description": description
        }
    }

    # Send the event announcement with buttons
    event_message = await channel.send(embed=build_event_embed(event_name), view=RoleSelectView(event_name, channel.guild.me))
    
    # Create a thread for this event
    thread = await event_message.create_thread(name=f"{event_name} Discussion", auto_archive_duration=60)  # Archive after 60 minutes of inactivity
    
    # Save message ID and thread ID for updating the announcement
    events[event_name]["message_id"] = event_message.id
    events[event_name]["thread_id"] = thread.id  # Store the thread ID
    
class EventModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create Event")

        # Event Name
        self.add_item(discord.ui.TextInput(label="Event Name", placeholder="Enter the event name", required=True))

        # Event Time
        self.add_item(discord.ui.TextInput(label="Event Time", placeholder="Enter time (HH:MM)", required=True))

        # Mount Type
        self.add_item(discord.ui.TextInput(label="Mount Type", placeholder="Enter mount type", required=True))

        # Description
        self.add_item(discord.ui.TextInput(label="Description", placeholder="Enter event description", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        # Extract data from modal inputs
        event_name = self.children[0].value
        event_time = self.children[1].value
        mount_type = self.children[2].value
        description = self.children[3].value or "No description provided."

        # Validate event_time format
        try:
            datetime.strptime(event_time, "%H:%M")
        except ValueError:
            await interaction.response.send_message("Invalid time format. Please use HH:MM (24-hour).", ephemeral=True)
            return

        # Create the event using the extracted data
        await create_event_from_modal(interaction.channel, event_name, event_time, mount_type, description)

        # Notify the user that the event was created
        await interaction.response.send_message(f"✅ Event **{event_name}** created successfully!", ephemeral=True)

# Command to trigger the modal form
@bot.command()
async def event(ctx):
    modal = EventModal()
    await ctx.send_modal(modal)
# Function to create the event after modal submission
async def create_event_from_modal(channel, event_name, event_time, mount_type, description):
    # Initialize the event with roles and details (reusing the same logic from your existing event creation)
    events[event_name] = {
        "roles": {role: None for role in event_templates[event_name]},
        "details": {
            "time": event_time,
            "mount_type": mount_type,
            "description": description
        }
    }

    # Send the event announcement with buttons
    event_message = await channel.send(embed=build_event_embed(event_name), view=RoleSelectView(event_name, channel.guild.me))

    # Create a thread for this event
    thread = await event_message.create_thread(name=f"{event_name} Discussion", auto_archive_duration=60)

    # Save message ID and thread ID for updating the announcement
    events[event_name]["message_id"] = event_message.id
    events[event_name]["thread_id"] = thread.id  # Store the thread ID


def build_event_embed(event_name):
    event_info = events[event_name]
    roles = event_info["roles"]
    details = event_info["details"]
    
    embed = discord.Embed(title=f"Event: **{event_name}**", description=details["description"], color=discord.Color.blue())
    embed.add_field(name="**Start Time:**", value=details["time"], inline=True)
    embed.add_field(name="**Mount Type:**", value=details["mount_type"], inline=True)

    # Simulate a table for roles
    role_lines = []
    for role, user in roles.items():
        if user:
            line = f"**{role}:** {user.mention}"
        else:
            line = f"**{role}:** Available"
        role_lines.append(line)

    # Join all role lines with newline for better readability
    embed.add_field(name="**Roles**", value="\n".join(role_lines), inline=False)
    
    return embed

@bot.event
async def on_message(message):
    # Ignore bot's own messages
    if message.author == bot.user:
        return
    
    # Check if the message is in the allowed channel
    if message.channel.id not in allowed_channels:
        return

    # Log the received message and channel for debugging
    print(f"Received message in channel {message.channel.id}: {message.content}")

    # Parse the message content
    content = message.content.strip().lower()

    # Example message format: "create event PvE_Blue_Chest at 18:00 mount Horse description A fun dungeon raid"
    if content.startswith("create event"):
        try:
            # Split the message content into components
            parts = content.split(" ")
            
            event_name = parts[2]  # 3rd word is the event name
            event_time = parts[4]  # 5th word is the event time
            mount_type = parts[6]  # 7th word is the mount type
            description = " ".join(parts[8:])  # Everything after the 8th word is the description
            
            # Create the event
            await create_event_from_message(message.channel, event_name, event_time, mount_type, description)
        except IndexError:
            await message.channel.send("Invalid format. Please use: `create event <event_name> at <time> mount <mount_type> description <description>`")
    
    # Process other bot commands normally
    await bot.process_commands(message)


async def send_event_reminder(event_name, channel_id):
    channel = bot.get_channel(channel_id)
    event_info = events[event_name]
    registered_users = [user.mention for user in event_info["roles"].values() if user is not None]
    
    if registered_users:
        await channel.send(f"The event {event_name} is starting now! Participants: {', '.join(registered_users)}")
    else:
        await channel.send(f"The event {event_name} is starting now! No participants registered.")

@tasks.loop(seconds=60)
async def check_event_times():
    current_time = datetime.now().strftime("%H:%M")
    for event_name, event_info in events.items():
        if event_info["details"]["time"] == current_time:
            # Get the channel ID where the event announcement should be sent
            event_channel_id = allowed_channels[0]  # Replace with your actual event channel ID
            await send_event_reminder(event_name, event_channel_id)
            del events[event_name]  # Optionally remove the event after notifying

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    check_event_times.start()  # Start the background task

load_dotenv()
token=os.getenv("DISCORD_BOT_TOKEN")
# Run the bot with your token
bot.run(token)

