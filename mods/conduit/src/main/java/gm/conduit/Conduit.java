package gm.conduit;

import eu.pb4.polymer.resourcepack.api.PolymerResourcePackUtils;
import gm.conduit.modules.ModulePush;
import gm.conduit.pack.LiveAssets;
import gm.conduit.provenance.Provenance;
import gm.conduit.retrogen.OrePatchQueue;
import gm.conduit.slots.NeutralSlots;
import net.fabricmc.api.ModInitializer;

public final class Conduit implements ModInitializer {
	public static final String MOD_ID = "conduit";
	public static final String NAMESPACE = "gm";

	@Override
	public void onInitialize() {
		PolymerResourcePackUtils.addModAssets(MOD_ID);
		PolymerResourcePackUtils.markAsRequired();
		Provenance.init();
		ProofOfLife.register();
		NeutralSlots.register();
		LiveAssets.register();
		OrePatchQueue.register();
		ModulePush.register();
	}
}
