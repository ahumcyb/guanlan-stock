"""Generate a dependency-free Xcode project with the Mac model file shared directly."""
import hashlib
import json
import plistlib
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
objects={}
existing=ROOT/'Guanlan.xcodeproj/project.pbxproj'
team_match=re.search(r'\"?DEVELOPMENT_TEAM\"?\s*=\s*\"?([A-Z0-9]{10})\"?\s*;',existing.read_text()) if existing.exists() else None


def ident(name):return hashlib.sha256(name.encode()).hexdigest()[:24].upper()
def add(label,isa,**values):
    key=ident(label);objects[key]=dict(isa=isa,**values);return key
def encode(value,level=0):
    if isinstance(value,dict):return '{\n'+''.join('  '*(level+1)+json.dumps(str(k))+" = "+encode(v,level+1)+';\n' for k,v in value.items())+'  '*level+'}'
    if isinstance(value,list):return '( '+', '.join(encode(v,level+1) for v in value)+' )'
    return str(value) if isinstance(value,int) else json.dumps(value,ensure_ascii=False)


sources=[];references=[]
for path in sorted((ROOT/'Sources').rglob('*.swift')):
    relative=path.relative_to(ROOT).as_posix()
    reference=add(relative,'PBXFileReference',lastKnownFileType='sourcecode.swift',path=relative,sourceTree='<group>')
    references.append(reference);sources.append(add(relative+' build','PBXBuildFile',fileRef=reference))
reference=add('SharedModels','PBXFileReference',lastKnownFileType='sourcecode.swift',name='Shared Mac Models.swift',path='../ashare-mac/macos/Models.swift',sourceTree='<group>')
references.append(reference);sources.append(add('SharedModels build','PBXBuildFile',fileRef=reference))
reference=add('RealtimeModels','PBXFileReference',lastKnownFileType='sourcecode.swift',name='Shared Realtime Models.swift',path='../ashare-mac/macos/RealtimeModels.swift',sourceTree='<group>')
references.append(reference);sources.append(add('RealtimeModels build','PBXBuildFile',fileRef=reference))
reference=add('DailyModels','PBXFileReference',lastKnownFileType='sourcecode.swift',name='Shared Daily Models.swift',path='../ashare-mac/macos/DailyModels.swift',sourceTree='<group>')
references.append(reference);sources.append(add('DailyModels build','PBXBuildFile',fileRef=reference))
product=add('Product','PBXFileReference',explicitFileType='wrapper.application',includeInIndex=0,path='Guanlan.app',sourceTree='BUILT_PRODUCTS_DIR')
assets=add('Assets','PBXFileReference',lastKnownFileType='folder.assetcatalog',path='Assets.xcassets',sourceTree='<group>')
references.append(assets)
source_phase=add('Sources phase','PBXSourcesBuildPhase',buildActionMask=2147483647,files=sources,runOnlyForDeploymentPostprocessing=0)
resource_phase=add('Resources phase','PBXResourcesBuildPhase',buildActionMask=2147483647,files=[add('Assets build','PBXBuildFile',fileRef=assets)],runOnlyForDeploymentPostprocessing=0)
framework_phase=add('Framework phase','PBXFrameworksBuildPhase',buildActionMask=2147483647,files=[],runOnlyForDeploymentPostprocessing=0)
products=add('Products','PBXGroup',children=[product],name='Products',sourceTree='<group>')
main=add('Main','PBXGroup',children=references+[products],sourceTree='<group>')
project_configs=[];target_configs=[]
for name in ['Debug','Release']:
    project_configs.append(add('Project '+name,'XCBuildConfiguration',name=name,buildSettings={'CLANG_ENABLE_MODULES':'YES','SWIFT_VERSION':'5.0','IPHONEOS_DEPLOYMENT_TARGET':'17.0'}))
    settings={'PRODUCT_BUNDLE_IDENTIFIER':'local.guanlan.ios.bennie','PRODUCT_NAME':'Guanlan','SWIFT_VERSION':'5.0',
        'SWIFT_OPTIMIZATION_LEVEL':'-Onone' if name=='Debug' else '-O','SWIFT_ACTIVE_COMPILATION_CONDITIONS':'DEBUG' if name=='Debug' else '',
        'SDKROOT':'iphoneos','SUPPORTED_PLATFORMS':'iphoneos iphonesimulator','TARGETED_DEVICE_FAMILY':'1,2',
        'INFOPLIST_FILE':'Info.plist','GENERATE_INFOPLIST_FILE':'NO','CODE_SIGN_STYLE':'Automatic','IPHONEOS_DEPLOYMENT_TARGET':'17.0',
        'ASSETCATALOG_COMPILER_APPICON_NAME':'AppIcon','CURRENT_PROJECT_VERSION':'6','MARKETING_VERSION':'1.4.0',
        'ENABLE_USER_SCRIPT_SANDBOXING':'YES','SWIFT_STRICT_CONCURRENCY':'minimal'}
    if team_match:settings['DEVELOPMENT_TEAM']=team_match[1]
    target_configs.append(add('Target '+name,'XCBuildConfiguration',name=name,buildSettings=settings))
project_list=add('Project configurations','XCConfigurationList',buildConfigurations=project_configs,defaultConfigurationIsVisible=0,defaultConfigurationName='Release')
target_list=add('Target configurations','XCConfigurationList',buildConfigurations=target_configs,defaultConfigurationIsVisible=0,defaultConfigurationName='Release')
target=add('Target','PBXNativeTarget',buildConfigurationList=target_list,buildPhases=[source_phase,framework_phase,resource_phase],buildRules=[],dependencies=[],name='Guanlan',productName='Guanlan',productReference=product,productType='com.apple.product-type.application')
project=add('Project','PBXProject',attributes={'BuildIndependentTargetsInParallel':'YES','LastUpgradeCheck':'2660'},buildConfigurationList=project_list,compatibilityVersion='Xcode 14.0',developmentRegion='zh-Hans',hasScannedForEncodings=0,knownRegions=['zh-Hans','en','Base'],mainGroup=main,productRefGroup=products,projectDirPath='',projectRoot='',targets=[target])
folder=ROOT/'Guanlan.xcodeproj';folder.mkdir(exist_ok=True)
(folder/'project.pbxproj').write_text('// !$*UTF8*$!\n'+encode(dict(archiveVersion=1,classes={},objectVersion=56,objects=objects,rootObject=project))+'\n')
schemes=folder/'xcshareddata/xcschemes';schemes.mkdir(parents=True,exist_ok=True)
reference=f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{target}" BuildableName="Guanlan.app" BlueprintName="Guanlan" ReferencedContainer="container:Guanlan.xcodeproj"/>'
(schemes/'Guanlan.xcscheme').write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2660" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="YES" buildForArchiving="YES" buildForAnalyzing="YES">{reference}</BuildActionEntry></BuildActionEntries></BuildAction>
<LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="NO" debugDocumentVersioning="YES" allowLocationSimulation="NO"><BuildableProductRunnable runnableDebuggingMode="0">{reference}</BuildableProductRunnable></LaunchAction>
<ProfileAction buildConfiguration="Release" shouldUseLaunchSchemeArgsEnv="YES" savedToolIdentifier="" useCustomWorkingDirectory="NO" debugDocumentVersioning="YES"><BuildableProductRunnable runnableDebuggingMode="0">{reference}</BuildableProductRunnable></ProfileAction>
<AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="YES"/>
</Scheme>''')
info=dict(CFBundleDevelopmentRegion='zh-Hans',CFBundleDisplayName='观澜选股',CFBundleName='Guanlan',CFBundleExecutable='$(EXECUTABLE_NAME)',CFBundleIdentifier='$(PRODUCT_BUNDLE_IDENTIFIER)',CFBundlePackageType='APPL',CFBundleShortVersionString='$(MARKETING_VERSION)',CFBundleVersion='$(CURRENT_PROJECT_VERSION)',LSRequiresIPhoneOS=True,UIApplicationSceneManifest={'UIApplicationSupportsMultipleScenes':False},UILaunchScreen={},UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight'],**{'UISupportedInterfaceOrientations~ipad':['UIInterfaceOrientationPortrait','UIInterfaceOrientationPortraitUpsideDown','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight']})
info['UTExportedTypeDeclarations']=[{'UTTypeIdentifier':'local.guanlan.connection','UTTypeDescription':'观澜服务器连接','UTTypeConformsTo':['public.json'],'UTTypeTagSpecification':{'public.filename-extension':['guanlan']}}]
info['CFBundleDocumentTypes']=[{'CFBundleTypeName':'观澜连接','CFBundleTypeRole':'Viewer','LSHandlerRank':'Owner','LSItemContentTypes':['local.guanlan.connection']}]
info['LSSupportsOpeningDocumentsInPlace']=True
info['CFBundleURLTypes']=[{'CFBundleURLName':'local.guanlan.alerts','CFBundleURLSchemes':['guanlan']}]
# iOS 17+ applies ATS to IP hosts. Permit this server's private CA evaluation;
# Connection.swift still requires HTTPS, TLS 1.2+, a paired anchor and exact IP.
info['NSAppTransportSecurity']={'NSExceptionDomains':{'106.14.125.189':{
    'NSExceptionAllowsInsecureHTTPLoads':True,'NSExceptionMinimumTLSVersion':'TLSv1.2',
    'NSExceptionRequiresForwardSecrecy':True}}}
with (ROOT/'Info.plist').open('wb') as output:plistlib.dump(info,output)
print('Xcode project generated with shared Mac models')
