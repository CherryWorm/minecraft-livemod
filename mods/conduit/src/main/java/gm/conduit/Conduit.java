package gm.conduit;

import eu.pb4.polymer.resourcepack.api.PolymerResourcePackUtils;
import gm.conduit.bridge.Bridge;
import gm.conduit.knowledge.Codex;
import gm.conduit.knowledge.Knowledge;
import gm.conduit.mobs.SlotMobs;
import gm.conduit.modules.ModulePush;
import gm.conduit.modules.ServerModuleHost;
import gm.conduit.pack.LiveAssets;
import gm.conduit.pack.PackStatus;
import gm.conduit.provenance.Provenance;
import gm.conduit.retrogen.BiomePatch;
import gm.conduit.retrogen.OrePatchQueue;
import gm.conduit.slots.NeutralSlots;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerLifecycleEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;

public final class Conduit implements ModInitializer {
	public static final String MOD_ID = "conduit";
	public static final String NAMESPACE = "gm";

	@Override
	public void onInitialize() {
		PolymerResourcePackUtils.addModAssets(MOD_ID);
		PolymerResourcePackUtils.markAsRequired();
		Provenance.init();
		NeutralSlots.register();
		SlotMobs.register();
		LiveAssets.register();
		PackStatus.register();
		Knowledge.register();
		Codex.register();
		OrePatchQueue.register();
		BiomePatch.registerPlacements();
		ModulePush.register();
		Bridge.register();
		ConduitCommands.register();
		KillSwitch.register();
		Chaos.register();

		ServerLifecycleEvents.SERVER_STARTED.register(server -> {
			ServerModuleHost.instance().start(server);
			ModulePush.loadOnStart();
		});
		ServerTickEvents.END_SERVER_TICK.register(server -> ServerModuleHost.instance().tick(server));
	}
}
