package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.Component;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.world.Container;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.state.BlockState;

import java.util.List;
import java.util.function.Consumer;

/**
 * What a server module can hook into. Names are the ones in the feature's manifest, such as
 * "ember_ore". The host resolves them, so module code never contains a slot ID.
 */
public interface ServerModuleContext {
	String moduleId();

	MinecraftServer server();

	void bindBlock(String name, BlockBehavior behavior);

	void bindItem(String name, ItemBehavior behavior);

	void bindMachine(String name, MachineBehavior behavior);

	void bindMob(String name, MobBehavior behavior);

	void onServerTick(Consumer<MinecraftServer> tick);

	/** Hears about things that happen anywhere in the world, so there's no need to poll for them each tick. */
	void listen(WorldEvents events);

	/** The block for a name in this feature's manifest, or for "other_feature/name". */
	Block block(String name);

	/** The item for a name in this feature's manifest, or for "other_feature/name". */
	Item item(String name);

	/** The entity type for a mob in this feature's manifest, or for "other_feature/name". */
	EntityType<?> mob(String name);

	/** The sound for a name in this feature's "sounds", or for "other_feature/name". */
	SoundEvent sound(String name);

	/**
	 * Plays one of those sounds at a spot, for everyone close enough to hear it. A volume above 1 carries further, and
	 * pitch runs from 0.5 to 2. To choose its volume slider or who hears it, use {@link #sound} with the game's own calls.
	 */
	void playSound(String name, Level level, BlockPos pos, float volume, float pitch);

	/**
	 * Checks what a player put in a machine against its recipes, and reports near misses. The machine is one of this feature's,
	 * or "other_feature/name" for another's. For a machine running by itself, like one fed by a hopper, the player is null,
	 * and then a recipe that has to be learned only works if the whole world shares what's learned and someone knows it.
	 */
	MachineAttempt attemptRecipe(Player player, String machine, List<ItemStack> inputs);

	/** Opens a menu made of chest slots, from 1 to 6 rows, which needs nothing on the player's computer. */
	void openMenu(ServerPlayer player, Component title, int rows, MenuBehavior behavior);

	/**
	 * Opens one of this feature's "panels", or "other_feature/name", drawn the way feature.json says. Its item slots have an inventory of
	 * their own, and whatever's left in it goes back to the player when it closes. It stays open however far away they go.
	 */
	void openPanel(ServerPlayer player, String name, PanelBehavior behavior);

	/** Opens a panel on this inventory, such as a machine, which closes when the player can no longer reach it. */
	void openPanel(ServerPlayer player, String name, Container container, PanelBehavior behavior);

	/** Opens a panel about something in the world, such as a mob to trade with, which closes when it dies or the player walks away. */
	void openPanel(ServerPlayer player, String name, Entity near, PanelBehavior behavior);

	/** Opens a book for a player to read, with no such item existing. A page holds about 230 characters. */
	void openBook(ServerPlayer player, String title, List<Component> pages);

	/** Examines a block for a player, teaching whatever any feature teaches for looking closely at it, as if they'd done it by hand. */
	void examine(ServerPlayer player, BlockState state);

	/** Examines a mob for a player in the same way. */
	void examine(ServerPlayer player, Entity target);

	/**
	 * Whether this block is as the world made it. Anything changed since isn't, whether by a player, a module, or the game itself, like
	 * grass spreading or sand falling. So the answer is safe to go by for leaving someone's building alone, but it can't say who did it.
	 */
	boolean isNatural(Level level, BlockPos pos);

	/**
	 * Tells any module listening for this, as "this_feature/topic". Modules can't share classes, so what's sent is a tag of
	 * plain values. Nobody listening is fine, and so is a listener that fails: this never finds out.
	 */
	void publish(String topic, CompoundTag message);

	/** Hears what another module publishes, or this one, by "other_feature/topic". It only goes on while this module is loaded. */
	void subscribe(String topic, Consumer<CompoundTag> listener);

	/** Whether a player knows one of this feature's knowledge entries. */
	boolean knows(Player player, String knowledge);

	/** Teaches a player one of this feature's knowledge entries, for discoveries a module detects itself. */
	void teach(ServerPlayer player, String knowledge);

	/** One of this feature's "dimensions", or "other_feature/name", to look at or change, or to send someone to a place of your own choosing. */
	ServerLevel dimension(String name);

	/**
	 * Sends a player to a dimension, at its spawn or the nearest safe ground to it, and remembers where they came from. In a dimension
	 * with nothing to stand on, it makes a small platform. To use that, or for a door of your own, this is all a portal has to call.
	 */
	void enterDimension(ServerPlayer player, String name);

	/** Sends a player back to where they entered a dimension from, or to wherever they'd respawn if that isn't known. Does nothing for someone who isn't in one. */
	void leaveDimension(ServerPlayer player);
}
