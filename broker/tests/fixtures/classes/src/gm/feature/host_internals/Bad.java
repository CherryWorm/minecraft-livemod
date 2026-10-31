package gm.feature.host_internals;

import gm.conduit.modules.ServerModuleHost;

/** Reaches past the API into the module host. */
public final class Bad {
	public static Object run() {
		return ServerModuleHost.instance().loadedModules();
	}
}
