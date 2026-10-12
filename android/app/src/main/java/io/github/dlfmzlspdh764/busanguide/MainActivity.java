package io.github.dlfmzlspdh764.busanguide;
import android.app.Activity; import android.content.Intent; import android.net.Uri; import android.os.Bundle;
import android.webkit.*;
public class MainActivity extends Activity {
  static final String HOME="https://dlfmzlspdh764-svg.github.io/busan-guide/";
  WebView w;
  @Override protected void onCreate(Bundle b){ super.onCreate(b); w=new WebView(this); setContentView(w);
    WebSettings s=w.getSettings(); s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true);
    s.setUserAgentString(s.getUserAgentString()+" BusanGuideApp/1.0");
    w.setWebViewClient(new WebViewClient(){
      @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r){ return handle(r.getUrl().toString()); }
      @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e){ if(r.isForMainFrame()) v.loadUrl("file:///android_asset/offline.html"); }
    });
    if(b!=null) w.restoreState(b); else w.loadUrl(HOME); }
  boolean handle(String u){
    if(u.startsWith(HOME)||u.startsWith("file:///android_asset/")) return false;
    try{ Intent i= u.startsWith("intent:")? Intent.parseUri(u,Intent.URI_INTENT_SCHEME): new Intent(Intent.ACTION_VIEW,Uri.parse(u));
      i.addCategory(Intent.CATEGORY_BROWSABLE); startActivity(i);
    }catch(Exception e){ if(u.startsWith("intent:")){ try{ String f=Intent.parseUri(u,Intent.URI_INTENT_SCHEME).getStringExtra("browser_fallback_url"); if(f!=null) startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(f))); }catch(Exception x){} } }
    return true; }
  @Override protected void onSaveInstanceState(Bundle o){ super.onSaveInstanceState(o); w.saveState(o); }
  @Override public void onBackPressed(){ if(w.canGoBack()) w.goBack(); else super.onBackPressed(); }
}
