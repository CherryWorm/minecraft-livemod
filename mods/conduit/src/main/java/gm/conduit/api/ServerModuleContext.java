package gm.conduit.api;

import net.minecraft.core.BlockPos;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.sounds.SoundEvent;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;

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

	/** Checks what a player put in one of this feature's machines against its recipes, and reports near misses. */
	MachineAttempt attemptRecipe(Player player, String machine, List<ItemStack> inputs);

	/** Whether a player knows one of this feature's knowledge entries. */
	boolean knows(Player player, String knowledge);

	/** Teaches a player one of this feature's knowledge entries, for discoveries a module detects itself. */
	void teach(ServerPlayer player, String knowledge);
}
