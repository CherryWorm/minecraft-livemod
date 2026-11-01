package gm.conduit;

import eu.pb4.polymer.resourcepack.api.PolymerResourcePackUtils;
import gm.conduit.bridge.Board;
import gm.conduit.bridge.Bridge;
import gm.conduit.dimensions.Dimensions;
import gm.conduit.knowledge.Codex;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.knowledge.KnownRecipes;
import gm.conduit.mobs.Minds;
import gm.conduit.mobs.SlotMobs;
import gm.conduit.modules.ModulePush;
import gm.conduit.modules.ServerModuleHost;
import gm.conduit.pack.LiveAssets;
import gm.conduit.pack.PackStatus;
import gm.conduit.pack.ServerNames;
import gm.conduit.provenance.Provenance;
import gm.conduit.retrogen.BiomePatch;
import gm.conduit.retrogen.OrePatchQueue;
import gm.conduit.panels.PanelNetwork;
import gm.conduit.slots.BlockModels;
import gm.conduit.slots.BlockSettings;
import gm.conduit.slots.MachineInventories;
import gm.conduit.slots.ItemDefaults;
import gm.conduit.slots.NeutralSlots;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.minecraft.network.chat.Component;
import net.minecraft.server.level.ServerPlayer;

import java.util.List;

public final class Conduit implements ModInitializer {
	public static final String MOD_ID = "conduit";
	public static final String NAMESPACE = "gm";

	@Override
	public void onInitialize() {
		PolymerResourcePackUtils.addModAssets(MOD_ID);
		PolymerResourcePackUtils.markAsRequired();
		Provenance.init();
		PasswordGate.register();
		Opening.register();
		NeutralSlots.register();
		ItemDefaults.register();
		SlotMobs.register();
		Minds.register();
		BlockModels.register();
		MachineInventories.register();
		BlockSettings.register();
		PanelNetwork.register();
		LiveAssets.register();
		ServerNames.register();
		PackStatus.register();
		Knowledge.register();
		KnownRecipes.register();
		Codex.register();
		Dimensions.register();
		OrePatchQueue.register();
		BiomePatch.registerPlacements();
		ServerModuleHost.register();
		ModulePush.register();
		Bridge.register();
		Board.register();
		ConduitCommands.register();
		KillSwitch.register();
		Chaos.register();

		ServerLifecycleEvents.SERVER_STARTING.register(server -> MixinCheck.run());
		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			ServerModuleHost.instance().start(server);
			ModulePush.loadOnStart();
		});
		ServerTickEvents.END_SERVER_TICK.register(server -> ServerModuleHost.instance().tick(server));
		// The game's own loop over players skips the next one each time someone leaves the list, and whoever's skipped just
		// loses the connection. The proxy can only hold someone who's been told it's a restart, so everyone gets told here.
		ServerLifecycleEvents.SERVER_STOPPING.register(server -> {
			for (ServerPlayer player : List.copyOf(server.getPlayerList().getPlayers())) {
				player.connection.disconnect(Component.translatable("multiplayer.disconnect.server_shutdown"));
			}
		});
	}
}
